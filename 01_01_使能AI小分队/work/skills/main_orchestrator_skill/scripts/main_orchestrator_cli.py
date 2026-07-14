# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent_runner import AgentRunner
from answer_validator import answer_from_result, build_answer_item, normalize_answer
from orchestrator_common import (
    GENERIC_TEXT_EXTS,
    HIGH_RISK_ANSWER,
    OFFICE_EXTS,
    TEXT_CODE_EXTS,
    append_jsonl,
    candidate_path,
    ensure_dir,
    make_question_log,
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
        filters = dict(classification.get("filters") or {})
        if str(classification.get("task_type") or "").startswith("answer_"):
            filters.setdefault("limit", self._knowledge_candidate_limit(classification))
        payload["filters"] = filters
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

    def _knowledge_candidate_limit(self, classification: Dict[str, Any]) -> int:
        task_type = str(classification.get("task_type") or "")
        if task_type == "answer_file_content_paths":
            return 200
        if task_type in {"answer_command_info", "answer_environment_info"}:
            return 100
        if task_type in {"answer_excel_summary", "answer_code_static_question"}:
            return 80
        return 60

    def _command_candidate_score(self, item: Dict[str, Any]) -> int:
        text = " ".join(
            str(item.get(key) or "")
            for key in ("path", "name", "stem", "category_dir", "extension", "file_type")
        ).casefold()
        score = 0
        command_terms = (
            "04_常用命令",
            "常用命令",
            "命令",
            "command",
            "cmd",
            "shell",
            "脚本",
            "script",
            "控制台",
            "终端",
            "客户端",
            "连接",
            "登录",
            "ssh",
            "gsql",
            "psql",
            "jdbc",
            "kubectl",
            "docker",
        )
        for term in command_terms:
            if term.casefold() in text:
                score += 12 if term in {"04_常用命令", "常用命令", "command"} else 6
        ext = str(item.get("extension") or "").lower().lstrip(".")
        if ext in {"md", "txt", "sh", "cmd", "sql", "conf", "ini", "log", "pdf"}:
            score += 3
        return score

    def _candidate_key(self, candidate: Dict[str, Any]) -> str:
        return candidate_path(candidate).casefold()

    def _merge_candidates(self, *groups: List[Dict[str, Any]], limit: int | None = None) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        seen = set()
        for group in groups:
            for item in group or []:
                if not isinstance(item, dict):
                    continue
                key = self._candidate_key(item)
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if limit and len(merged) >= limit:
                    return merged
        return merged

    def _candidate_pool(self, question: Dict[str, Any], classification: Dict[str, Any], family: str | None = None) -> List[Dict[str, Any]]:
        candidates = self._recall_candidates(question, classification)
        if classification.get("candidate_strategy") == "targeted_or_all":
            files_in_question = classification.get("files") or []
            if not files_in_question or len(candidates) < 1:
                candidates = self._all_candidates_by_family(question, family or str(classification.get("target_agent") or "text_code"))
        return candidates

    def _expand_knowledge_candidates(self, question: Dict[str, Any], classification: Dict[str, Any], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        limit = self._knowledge_candidate_limit(classification)
        index = self._build_index(question)
        files = [item for item in index.get("files") or [] if isinstance(item, dict)]
        parseable_exts = OFFICE_EXTS | TEXT_CODE_EXTS | GENERIC_TEXT_EXTS
        broad_candidates = []
        for item in files:
            ext = str(item.get("extension") or item.get("file_type") or "").lower().lstrip(".")
            if ext in parseable_exts:
                broad_candidates.append(item)
        priority_candidates: List[Dict[str, Any]] = []
        if str(classification.get("task_type") or "") == "answer_command_info":
            priority_candidates = sorted(
                (item for item in broad_candidates if self._command_candidate_score(item) > 0),
                key=lambda item: (-self._command_candidate_score(item), str(item.get("path") or "").casefold()),
            )
        expanded = self._merge_candidates(candidates, priority_candidates, broad_candidates, limit=limit)
        append_jsonl(
            self.run_log_dir / "main_orchestrator_agent.log",
            make_question_log(
                str(question.get("id") or ""),
                "knowledge_candidates_expanded",
                original_count=len(candidates),
                expanded_count=len(expanded),
                limit=limit,
            ),
        )
        return expanded

    def _filter_allowed_candidates(self, question: Dict[str, Any], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        allowed: List[Dict[str, Any]] = []
        denied: List[Dict[str, Any]] = []
        for index, candidate in enumerate(candidates):
            path = candidate_path(candidate)
            if not path:
                continue
            payload = self._base_payload(question, "check_resource")
            payload["resource"] = {"kind": "file", "value": path}
            result = self.runner.run_cli(
                f"{question['id']}_security_candidate_{index + 1}",
                self.runner.script_path("security_guard_skill", "security_agent_cli.py"),
                payload,
            )
            if result.get("decision") == "deny" or result.get("status") == "error":
                denied.append({"path": path, "reason": result.get("reason") or result.get("error_msg")})
                continue
            allowed.append(candidate)
        if denied:
            append_jsonl(
                self.run_log_dir / "main_orchestrator_agent.log",
                make_question_log(str(question.get("id") or ""), "knowledge_candidates_filtered_by_security", denied=denied[:20], denied_count=len(denied)),
            )
        return allowed

    def _candidate_abs_path(self, candidate: Dict[str, Any]) -> Optional[Path]:
        raw_abs = candidate.get("absolute_path")
        if raw_abs:
            path = Path(str(raw_abs))
        else:
            raw = candidate_path(candidate)
            if not raw:
                return None
            path = Path(raw)
            if not path.is_absolute():
                normalized = raw.replace("\\", "/")
                if normalized.startswith("docs/"):
                    path = self.wiki_root / normalized
                else:
                    path = self.docs_root / normalized
        try:
            resolved = path.resolve()
            resolved.relative_to(self.docs_root.resolve())
            return resolved
        except Exception:
            return None

    def _decode_generic_text(self, path: Path) -> str:
        if path.suffix.lower() == ".pdf":
            return self._decode_pdf_text(path)
        data = path.read_bytes()[:512_000]
        if b"\x00" in data[:4096]:
            return ""
        for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="ignore")

    def _decode_pdf_text(self, path: Path) -> str:
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            pages = []
            for page in reader.pages[:20]:
                pages.append(page.extract_text() or "")
            text = "\n".join(page for page in pages if page.strip())
            if text.strip():
                return text
        except Exception as exc:
            append_jsonl(
                self.run_log_dir / "main_orchestrator_agent.log",
                make_question_log("", "pdf_text_pypdf_failed", path=str(path), error=str(exc)),
            )

        data = path.read_bytes()[:1_000_000]
        text = data.decode("latin-1", errors="ignore")
        streams = re.findall(r"BT(.*?)ET", text, flags=re.DOTALL)
        parts = []
        for stream in streams:
            parts.extend(re.findall(r"\(([^()]*)\)", stream))
        printable = "\n".join(part.replace("\\(", "(").replace("\\)", ")") for part in parts)
        if printable.strip():
            return printable
        return ""

    def _generic_text_context(self, question: Dict[str, Any], candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        blocks: List[Dict[str, Any]] = []
        for candidate in candidates:
            ext = str(candidate.get("extension") or "").lower().lstrip(".")
            if ext not in GENERIC_TEXT_EXTS:
                continue
            path = self._candidate_abs_path(candidate)
            if not path or not path.exists() or not path.is_file():
                continue
            try:
                text = self._decode_generic_text(path)
            except Exception as exc:
                append_jsonl(
                    self.run_log_dir / "main_orchestrator_agent.log",
                    make_question_log(str(question.get("id") or ""), "generic_text_read_failed", path=candidate_path(candidate), error=str(exc)),
                )
                continue
            text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
            if not text:
                continue
            source = candidate_path(candidate)
            chunks = [text[i : i + 2500] for i in range(0, min(len(text), 10000), 2500)]
            for chunk_index, chunk in enumerate(chunks[:4], start=1):
                if chunk.strip():
                    blocks.append(
                        {
                            "source": source,
                            "file_type": ext,
                            "kind": "text",
                            "location": f"chunk:{chunk_index}",
                            "text": chunk.strip(),
                            "metadata": {"generic_text_fallback": True},
                        }
                    )
        if blocks:
            append_jsonl(
                self.run_log_dir / "main_orchestrator_agent.log",
                make_question_log(str(question.get("id") or ""), "generic_text_context_built", block_count=len(blocks)),
            )
        return blocks

    def _run_annotation_task(self, question: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
        family = str(classification.get("target_agent") or "text_code")
        if family == "all":
            return self._run_annotation_task_all(question, classification)

        return self._run_annotation_task_for_family(question, classification, family)

    def _annotation_task_type_for_family(self, category: str, family: str, fallback_task_type: str) -> str:
        if category == "filter_annotation":
            return "filter_comments" if family == "office" else "filter_todos"
        if category == "count_annotation":
            return "count_comments" if family == "office" else "count_todos"
        if category == "fix_annotation":
            return "fix_comments" if family == "office" else "fix_todos"
        return fallback_task_type

    def _run_annotation_task_for_family(self, question: Dict[str, Any], classification: Dict[str, Any], family: str) -> Dict[str, Any]:
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
        task_type = self._annotation_task_type_for_family(
            str(classification.get("category") or ""),
            family,
            str(classification.get("task_type") or ""),
        )
        payload = self._base_payload(question, task_type)
        payload["candidate_files"] = selected
        payload["filters"] = classification.get("filters") or {}
        result = self.runner.run_cli(
            f"{question['id']}_{family}_{task_type}",
            self.runner.script_path(skill_name, script_name),
            payload,
            timeout=600,
        )
        return answer_from_result(result)

    def _run_annotation_task_all(self, question: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
        category = str(classification.get("category") or "")
        families = ["office", "text_code"]

        if category == "fix_annotation":
            for family in families:
                answer = self._run_annotation_task_for_family(question, classification, family)
                if "source" in answer and "target" in answer:
                    return answer
            return {"datas": []}

        answers = [self._run_annotation_task_for_family(question, classification, family) for family in families]
        if category == "count_annotation":
            count = 0
            for answer in answers:
                if "count" in answer:
                    count += int(answer.get("count") or 0)
                elif isinstance(answer.get("datas"), list):
                    count += len(answer.get("datas") or [])
            return {"count": count}

        datas: List[str] = []
        for answer in answers:
            values = answer.get("datas") if isinstance(answer, dict) else None
            if isinstance(values, list):
                datas.extend(str(item) for item in values if item is not None)
        return {"datas": unique_preserve_order(datas)}

    def _run_knowledge_task(self, question: Dict[str, Any], classification: Dict[str, Any]) -> Dict[str, Any]:
        candidates = self._candidate_pool(question, classification)
        if not candidates:
            candidates = self._recall_candidates(question, classification)
        candidates = self._expand_knowledge_candidates(question, classification, candidates)
        candidates = self._filter_allowed_candidates(question, candidates)
        if not candidates:
            return {"datas": []}

        split = split_candidates(candidates)
        agent_results: List[Dict[str, Any]] = []
        if str(classification.get("task_type") or "") == "answer_excel_summary":
            excel_candidates = [
                item for item in split["office"] if str(item.get("extension") or "").lower().lstrip(".") in {"xls", "xlsx"}
            ]
            if excel_candidates:
                excel_payload = self._base_payload(question, "excel_analyze")
                excel_payload["candidate_files"] = excel_candidates
                excel_payload["filters"] = classification.get("filters") or {}
                excel_result = self.runner.run_cli(
                    f"{question['id']}_office_excel_analyze",
                    self.runner.script_path("office_document_skill", "office_agent_cli.py"),
                    excel_payload,
                    timeout=600,
                )
                agent_results.append(excel_result)
                excel_answer = answer_from_result(excel_result)
                if "source" in excel_answer and "target" in excel_answer:
                    return excel_answer

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

        generic_context_blocks = self._generic_text_context(question, split["other"])
        index = self.index_result or self._build_index(question)
        qa_payload = self._base_payload(question, str(classification.get("task_type") or "answer_from_context"))
        qa_payload["candidate_files"] = candidates
        qa_payload["agent_results"] = agent_results
        qa_payload["context_blocks"] = generic_context_blocks
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
