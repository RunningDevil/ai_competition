# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_runner import AgentRunner
from answer_validator import answer_from_result, build_answer_item, normalize_answer
from orchestrator_common import (
    HIGH_RISK_ANSWER,
    OFFICE_EXTS,
    TEXT_CODE_EXTS,
    append_jsonl,
    candidate_path,
    ensure_dir,
    make_question_log,
    normalize_path_text,
    path_for_payload,
    resolve_maybe_relative,
    resolve_project_root,
    resolve_wiki_root,
    split_candidates,
    timestamp,
    unique_preserve_order,
)
from question_classifier import classify_question
from question_loader import derive_output_file, load_questions, write_answers
from trace_collector import collect_trace


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


class MainOrchestrator:
    def __init__(self, project_root: Path, wiki_root: Path, run_log_dir: Path) -> None:
        self.project_root = project_root
        self.wiki_root = wiki_root
        self.docs_root = wiki_root / "docs"
        self.output_root = wiki_root / "output"
        self.fixed_root = self.output_root / "fixed"
        self.permission_path = wiki_root / "Permission.json"
        self.run_log_dir = run_log_dir
        self.runner = AgentRunner(project_root, run_log_dir)
        self.index_result: Optional[Dict[str, Any]] = None
        self.docs_resource_allowed: Optional[bool] = None

    def process_question(self, question: Dict[str, Any]) -> Dict[str, Any]:
        qid = str(question.get("id") or "")
        title = str(question.get("title") or "")
        append_jsonl(self.run_log_dir / "main_orchestrator_agent.log", make_question_log(qid, "start", title=title))

        security = self._check_question(question)
        if security.get("decision") == "deny" or security.get("status") == "error":
            answer = answer_from_result(security)
            append_jsonl(self.run_log_dir / "main_orchestrator_agent.log", make_question_log(qid, "security_denied", answer=answer, reason=security.get("reason")))
            return build_answer_item(question, answer)

        classification = classify_question(question)
        append_jsonl(self.run_log_dir / "question_classification.jsonl", {"question_id": qid, "title": title, "classification": classification})

        try:
            answer = self._dispatch(question, classification)
        except Exception as exc:
            append_jsonl(self.run_log_dir / "main_orchestrator_agent.log", make_question_log(qid, "dispatch_error", error=str(exc)))
            answer = {"datas": []}

        item = build_answer_item(question, answer)
        append_jsonl(self.run_log_dir / "main_orchestrator_agent.log", make_question_log(qid, "done", answer=item["answer"]))
        return item

    def _dispatch(self, question: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
        category = classification.get("category")
        if category == "file_count":
            return self._run_file_index_task(question, "count_by_type", classification)
        if category == "find_path":
            return self._run_file_index_task(question, "find_path", classification)
        if category in {"filter_annotation", "count_annotation", "fix_annotation"}:
            return self._run_annotation_task(question, classification)
        return self._run_knowledge_task(question, classification)

    def _check_question(self, question: Dict[str, Any]) -> Dict[str, Any]:
        payload = self._base_payload(question, "check_question")
        return self.runner.run_cli(
            f"{question['id']}_security_question",
            self.runner.script_path("security_guard_skill", "security_agent_cli.py"),
            payload,
        )

    def _ensure_docs_resource(self, question: Dict[str, Any]) -> bool:
        if self.docs_resource_allowed is not None:
            return self.docs_resource_allowed
        payload = self._base_payload(question, "check_resource")
        payload["resource"] = {"kind": "dir", "value": "docs"}
        result = self.runner.run_cli(
            f"{question['id']}_security_docs",
            self.runner.script_path("security_guard_skill", "security_agent_cli.py"),
            payload,
        )
        self.docs_resource_allowed = result.get("decision") != "deny" and result.get("status") == "ok"
        return self.docs_resource_allowed

    def _check_candidate_resources(self, question: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        resources = [{"kind": "file", "value": candidate_path(item)} for item in candidates if candidate_path(item)]
        if not resources:
            return None
        payload = self._base_payload(question, "batch_check_resources")
        payload["resources"] = resources
        result = self.runner.run_cli(
            f"{question['id']}_security_candidates",
            self.runner.script_path("security_guard_skill", "security_agent_cli.py"),
            payload,
        )
        if result.get("decision") == "deny" or result.get("status") == "error":
            return answer_from_result(result)
        return None

    def _run_file_index_task(self, question: Dict[str, Any], task_type: str, classification: Dict[str, Any]) -> Dict[str, Any]:
        if not self._ensure_docs_resource(question):
            return HIGH_RISK_ANSWER
        payload = self._base_payload(question, task_type)
        payload["filters"] = classification.get("filters") or {}
        result = self.runner.run_cli(
            f"{question['id']}_file_index_{task_type}",
            self.runner.script_path("file_index_skill", "file_index_agent_cli.py"),
            payload,
        )
        return answer_from_result(result)

    def _build_index(self, question: Dict[str, Any]) -> Dict[str, Any]:
        if self.index_result is not None:
            return self.index_result
        if not self._ensure_docs_resource(question):
            self.index_result = {"status": "error", "files": [], "summary": {}, "answer": HIGH_RISK_ANSWER}
            return self.index_result
        payload = self._base_payload(question, "build_index")
        payload["force_rebuild"] = False
        self.index_result = self.runner.run_cli(
            f"{question['id']}_file_index_build",
            self.runner.script_path("file_index_skill", "file_index_agent_cli.py"),
            payload,
        )
        return self.index_result

    def _recall_candidates(self, question: Dict[str, Any], classification: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self._ensure_docs_resource(question):
            return []
        payload = self._base_payload(question, "recall_candidates")
        payload["filters"] = classification.get("filters") or {}
        result = self.runner.run_cli(
            f"{question['id']}_file_index_recall",
            self.runner.script_path("file_index_skill", "file_index_agent_cli.py"),
            payload,
        )
        candidates = result.get("candidate_files") or []
        return [item for item in candidates if isinstance(item, dict)]

    def _all_candidates_by_family(self, question: Dict[str, Any], family: str) -> List[Dict[str, Any]]:
        index = self._build_index(question)
        files = index.get("files") or []
        target_exts = OFFICE_EXTS if family == "office" else TEXT_CODE_EXTS
        result = []
        for item in files:
            if not isinstance(item, dict):
                continue
            ext = str(item.get("extension") or item.get("file_type") or "").lower().lstrip(".")
            if ext in target_exts:
                result.append(item)
        return result

    def _candidate_pool(self, question: Dict[str, Any], classification: Dict[str, Any], family: str | None = None) -> List[Dict[str, Any]]:
        candidates = self._recall_candidates(question, classification)
        if classification.get("candidate_strategy") == "targeted_or_all":
            files_in_question = classification.get("files") or []
            if not files_in_question or len(candidates) < 1:
                candidates = self._all_candidates_by_family(question, family or str(classification.get("target_agent") or "text_code"))
        return candidates

    def _run_annotation_task(self, question: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
        family = str(classification.get("target_agent") or "text_code")
        candidates = self._candidate_pool(question, classification, family)
        split = split_candidates(candidates)
        selected = split["office"] if family == "office" else split["text_code"]
        if not selected:
            return {"datas": []}
        denied_answer = self._check_candidate_resources(question, selected)
        if denied_answer:
            return denied_answer

        skill_name = "office_document_skill" if family == "office" else "text_code_skill"
        script_name = "office_agent_cli.py" if family == "office" else "text_code_agent_cli.py"
        payload = self._base_payload(question, str(classification.get("task_type")))
        payload["candidate_files"] = selected
        payload["filters"] = classification.get("filters") or {}
        result = self.runner.run_cli(
            f"{question['id']}_{family}_{classification.get('task_type')}",
            self.runner.script_path(skill_name, script_name),
            payload,
            timeout=600,
        )
        return answer_from_result(result)

    def _run_knowledge_task(self, question: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
        candidates = self._candidate_pool(question, classification)
        if not candidates:
            candidates = self._recall_candidates(question, classification)
        candidates = candidates[:20]
        denied_answer = self._check_candidate_resources(question, candidates)
        if denied_answer:
            return denied_answer

        split = split_candidates(candidates)
        agent_results: List[Dict[str, Any]] = []
        if split["office"]:
            office_payload = self._base_payload(question, "provide_qa_context")
            office_payload["candidate_files"] = split["office"]
            office_payload["filters"] = classification.get("filters") or {}
            agent_results.append(
                self.runner.run_cli(
                    f"{question['id']}_office_qa_context",
                    self.runner.script_path("office_document_skill", "office_agent_cli.py"),
                    office_payload,
                    timeout=600,
                )
            )
        if split["text_code"]:
            text_payload = self._base_payload(question, "provide_qa_context")
            text_payload["candidate_files"] = split["text_code"]
            text_payload["filters"] = classification.get("filters") or {}
            agent_results.append(
                self.runner.run_cli(
                    f"{question['id']}_text_qa_context",
                    self.runner.script_path("text_code_skill", "text_code_agent_cli.py"),
                    text_payload,
                    timeout=600,
                )
            )

        index = self.index_result or self._build_index(question)
        qa_payload = self._base_payload(question, str(classification.get("task_type") or "answer_from_context"))
        qa_payload["candidate_files"] = candidates
        qa_payload["agent_results"] = agent_results
        qa_payload["index_summary"] = index.get("summary") or {}
        qa_payload["filters"] = classification.get("filters") or {}
        result = self.runner.run_cli(
            f"{question['id']}_knowledge_qa",
            self.runner.script_path("knowledge_qa_skill", "knowledge_qa_agent_cli.py"),
            qa_payload,
            timeout=300,
        )
        return answer_from_result(result)

    def _base_payload(self, question: Dict[str, Any], task_type: str) -> Dict[str, Any]:
        return {
            "question_id": question.get("id"),
            "question_title": question.get("title"),
            "task_type": task_type,
            "wiki_root": str(self.wiki_root),
            "docs_root": str(self.docs_root),
            "output_root": str(self.output_root),
            "fixed_root": str(self.fixed_root),
            "permission_path": str(self.permission_path),
            "safety": {"resource_checked": True},
            "run_log_dir": str(self.run_log_dir),
        }


def run(args: argparse.Namespace) -> Dict[str, Any]:
    project_root = resolve_project_root(args.project_root)
    wiki_root = resolve_wiki_root(project_root, args.wiki_root)
    question_file = resolve_maybe_relative(args.question_file, project_root)
    run_name = args.run_name or timestamp()
    run_log_dir = Path(args.run_log_dir).resolve() if args.run_log_dir else (project_root / "logs" / run_name).resolve()
    ensure_dir(run_log_dir)
    ensure_dir(project_root / "logs" / "trace")
    ensure_dir(wiki_root / "output")
    ensure_dir(wiki_root / "output" / "fixed")

    output_file = resolve_maybe_relative(args.output_file, project_root) if args.output_file else derive_output_file(question_file, wiki_root)
    questions = load_questions(question_file)
    orchestrator = MainOrchestrator(project_root, wiki_root, run_log_dir)

    answers = [orchestrator.process_question(question) for question in questions]
    write_answers(output_file, answers)

    summary = {
        "status": "ok",
        "project_root": str(project_root),
        "wiki_root": str(wiki_root),
        "question_file": str(question_file),
        "output_file": str(output_file),
        "run_log_dir": str(run_log_dir),
        "question_count": len(questions),
        "answer_count": len(answers),
    }
    trace_path = collect_trace(run_log_dir, project_root / "logs" / "trace", run_name, summary)
    summary["trace_path"] = str(trace_path)
    append_jsonl(run_log_dir / "main_orchestrator_agent.log", {"summary": summary})
    return summary


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Main orchestrator CLI for LLM-WIKI")
    parser.add_argument("--question-file", required=True, help="Path to llm-wiki/question/group-*.md")
    parser.add_argument("--project-root", help="Submission project root. Defaults to script-derived root.")
    parser.add_argument("--wiki-root", help="Path to llm-wiki root. Defaults to project-root/llm-wiki or known judge path.")
    parser.add_argument("--output-file", help="Optional answer output path. Defaults to llm-wiki/output/group-*-answer.md")
    parser.add_argument("--run-log-dir", help="Optional run log directory. Defaults to logs/{timestamp}.")
    parser.add_argument("--run-name", help="Optional timestamp/run name for trace log.")
    args = parser.parse_args(argv)

    try:
        result = run(args)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        return 0
    except Exception as exc:
        error = {"status": "error", "reason": str(exc)}
        sys.stdout.write(json.dumps(error, ensure_ascii=False, indent=2) + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
