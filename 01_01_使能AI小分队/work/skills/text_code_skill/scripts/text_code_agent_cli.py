# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from code_static_analyzer import analyze_text_code, summarize_risk_level
from text_code_common import (
    SUPPORTED_EXTS,
    append_log,
    ensure_resource_checked,
    filter_todos,
    get_extension,
    make_base_result,
    make_error,
    read_json_file,
    resolve_candidate_path,
    todos_to_answer,
    write_json_file,
)
from text_fixer import conservative_fix
from text_reader import extract_text_blocks
from todo_extractor import extract_todos_from_text


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


SUPPORTED_TASKS = {
    "extract_text",
    "extract_todos",
    "filter_todos",
    "count_todos",
    "fix_todos",
    "static_analyze",
    "provide_qa_context",
}


def _load_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if args.input_file:
        return read_json_file(args.input_file)
    if args.input_json:
        return json.loads(args.input_json)
    raise ValueError("either --input-json or --input-file is required")


def _collect_candidates(payload: Dict[str, Any], logs: List[str]) -> List[Path]:
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    paths: List[Path] = []
    for candidate in payload.get("candidate_files") or []:
        path = resolve_candidate_path(candidate, wiki_root)
        ext = get_extension(path)
        if ext not in SUPPORTED_EXTS:
            logs.append(f"Skipped non-text/code candidate: {path}")
            continue
        if not path.exists():
            logs.append(f"Candidate does not exist: {path}")
            continue
        paths.append(path)
    return paths


def _extract_texts(payload: Dict[str, Any], candidate_paths: List[Path], logs: List[str]) -> List[Dict[str, Any]]:
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    texts: List[Dict[str, Any]] = []
    for path in candidate_paths:
        try:
            texts.extend(extract_text_blocks(path, wiki_root, logs))
        except Exception as exc:
            logs.append(f"Text extraction failed for {path}: {exc}")
    return texts


def _extract_todos(payload: Dict[str, Any], candidate_paths: List[Path], logs: List[str]) -> List[Dict[str, Any]]:
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    todos: List[Dict[str, Any]] = []
    for path in candidate_paths:
        try:
            todos.extend(extract_todos_from_text(path, wiki_root, logs))
        except Exception as exc:
            logs.append(f"TODO extraction failed for {path}: {exc}")
    return todos


def _static_analyze(payload: Dict[str, Any], candidate_paths: List[Path], logs: List[str]) -> List[Dict[str, Any]]:
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    risks: List[Dict[str, Any]] = []
    for path in candidate_paths:
        try:
            risks.extend(analyze_text_code(path, wiki_root, logs))
        except Exception as exc:
            logs.append(f"Static analysis failed for {path}: {exc}")
    return risks


def _run_fix(payload: Dict[str, Any], candidate_paths: List[Path], logs: List[str]) -> Dict[str, Any]:
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    fixed_root = payload.get("fixed_root")
    filters = payload.get("filters") or {}
    for path in candidate_paths:
        todos = extract_todos_from_text(path, wiki_root, logs)
        if filters:
            todos = filter_todos(todos, filters)
        result = conservative_fix(path, wiki_root, fixed_root, todos, logs)
        if result.get("status") == "ok":
            return result
    return make_error("fix_todos", "No text/code TODO could be reliably fixed", logs)


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    task_type = str(payload.get("task_type") or "").strip()
    logs: List[str] = []
    run_log_dir = payload.get("run_log_dir")
    if task_type not in SUPPORTED_TASKS:
        result = make_error(task_type or "unknown", f"unsupported task_type: {task_type}", logs)
    else:
        ok, error = ensure_resource_checked(payload)
        if not ok:
            result = make_error(task_type, error, logs)
        else:
            candidate_paths = _collect_candidates(payload, logs)
            if not candidate_paths:
                result = make_error(task_type, "no valid text/code candidate files", logs)
            elif task_type in {"extract_text", "provide_qa_context"}:
                result = make_base_result(task_type)
                result["texts"] = _extract_texts(payload, candidate_paths, logs)
                if task_type == "provide_qa_context":
                    result["todos"] = _extract_todos(payload, candidate_paths, logs)
                    result["risks"] = _static_analyze(payload, candidate_paths, logs)
                    result["risk_level"] = summarize_risk_level(result["risks"])
                result["answer"] = {"datas": [item["text"] for item in result["texts"]]}
            elif task_type in {"extract_todos", "filter_todos"}:
                todos = _extract_todos(payload, candidate_paths, logs)
                if task_type == "filter_todos":
                    todos = filter_todos(todos, payload.get("filters") or {})
                result = make_base_result(task_type)
                result["todos"] = todos
                result["answer"] = todos_to_answer(todos)
            elif task_type == "count_todos":
                todos = _extract_todos(payload, candidate_paths, logs)
                todos = filter_todos(todos, payload.get("filters") or {}) if payload.get("filters") else todos
                result = make_base_result(task_type)
                result["todos"] = todos
                result["answer"] = {"count": len(todos)}
            elif task_type == "static_analyze":
                risks = _static_analyze(payload, candidate_paths, logs)
                result = make_base_result(task_type)
                result["risks"] = risks
                result["risk_level"] = summarize_risk_level(risks)
                result["answer"] = {"datas": [item["text"] for item in risks]}
            elif task_type == "fix_todos":
                result = _run_fix(payload, candidate_paths, logs)
            else:
                result = make_error(task_type, f"unsupported task_type: {task_type}", logs)

    result["logs"] = list(dict.fromkeys((result.get("logs") or []) + logs))
    append_log(run_log_dir, "text_code_agent.log", {"question_id": payload.get("question_id"), "task_type": task_type, "status": result.get("status"), "logs": result.get("logs")})
    append_log(run_log_dir, "text_code_agent_result.jsonl", result)
    return result


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Text/code skill CLI for LLM-WIKI")
    parser.add_argument("--input-json", help="JSON payload string")
    parser.add_argument("--input-file", help="Path to JSON payload file")
    parser.add_argument("--output-file", help="Optional path to write JSON result")
    args = parser.parse_args(argv)

    try:
        payload = _load_payload(args)
        result = run(payload)
    except Exception as exc:
        result = make_error("unknown", str(exc), [])

    if args.output_file:
        write_json_file(args.output_file, result)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
