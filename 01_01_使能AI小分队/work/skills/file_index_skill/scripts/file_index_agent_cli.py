# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from file_index_common import (
    apply_metadata_filters,
    append_log,
    count_by_category,
    count_by_extension,
    ensure_resource_checked,
    filter_extensions,
    make_base_result,
    make_error,
    read_json_file,
    resolve_docs_root,
    write_json_file,
)
from index_builder import build_or_load_index
from recall_rules import extract_extensions, find_paths, recall_candidates


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


SUPPORTED_TASKS = {
    "build_index",
    "count_by_type",
    "find_path",
    "recall_candidates",
    "summarize_index",
}


def _load_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if args.input_file:
        return read_json_file(args.input_file)
    if args.input_json:
        return json.loads(args.input_json)
    raise ValueError("either --input-json or --input-file is required")


def _load_index(payload: Dict[str, Any], logs: List[str], force: bool = False):
    docs_root = resolve_docs_root(payload)
    return build_or_load_index(docs_root, payload.get("run_log_dir"), force=force, logs=logs)


def _run_build_index(payload: Dict[str, Any], logs: List[str]) -> Dict[str, Any]:
    files, summary, index_path = _load_index(payload, logs, force=bool(payload.get("force_rebuild")))
    result = make_base_result("build_index")
    result["summary"] = summary
    result["files"] = apply_metadata_filters(files, payload)
    result["index_path"] = index_path
    result["logs"] = logs
    return result


def _target_extensions(payload: Dict[str, Any]) -> List[str]:
    explicit = filter_extensions(payload)
    if explicit:
        return explicit
    return extract_extensions(str(payload.get("question_title") or ""))


def _run_count_by_type(payload: Dict[str, Any], logs: List[str]) -> Dict[str, Any]:
    files, summary, index_path = _load_index(payload, logs)
    filtered = apply_metadata_filters(files, payload)
    counts = count_by_extension(filtered, countable_only=True)
    targets = _target_extensions(payload)
    answer = {ext: counts.get(ext, 0) for ext in targets} if targets else counts
    result = make_base_result("count_by_type")
    result["answer"] = answer
    result["summary"] = {"total_files": len(filtered), "counts": counts}
    result["index_path"] = index_path
    result["logs"] = logs
    return result


def _run_find_path(payload: Dict[str, Any], logs: List[str]) -> Dict[str, Any]:
    files, summary, index_path = _load_index(payload, logs)
    paths = find_paths(files, str(payload.get("question_title") or ""), payload)
    result = make_base_result("find_path")
    result["answer"] = {"datas": paths}
    result["candidate_files"] = paths
    result["summary"] = summary
    result["index_path"] = index_path
    result["logs"] = logs
    return result


def _run_recall_candidates(payload: Dict[str, Any], logs: List[str]) -> Dict[str, Any]:
    files, summary, index_path = _load_index(payload, logs)
    candidates = recall_candidates(files, str(payload.get("question_title") or ""), payload)
    result = make_base_result("recall_candidates")
    result["answer"] = {"datas": [item["path"] for item in candidates]}
    result["candidate_files"] = candidates
    result["summary"] = summary
    result["index_path"] = index_path
    result["logs"] = logs
    return result


def _run_summarize_index(payload: Dict[str, Any], logs: List[str]) -> Dict[str, Any]:
    files, summary, index_path = _load_index(payload, logs)
    filtered = apply_metadata_filters(files, payload)
    result = make_base_result("summarize_index")
    result["summary"] = {
        "total_files": len(filtered),
        "counts": count_by_extension(filtered, countable_only=True),
        "all_extension_counts": count_by_extension(filtered, countable_only=False),
        "categories": count_by_category(filtered),
    }
    result["answer"] = {"datas": [json.dumps(result["summary"], ensure_ascii=False)]}
    result["index_path"] = index_path
    result["logs"] = logs
    return result


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
            try:
                if task_type == "build_index":
                    result = _run_build_index(payload, logs)
                elif task_type == "count_by_type":
                    result = _run_count_by_type(payload, logs)
                elif task_type == "find_path":
                    result = _run_find_path(payload, logs)
                elif task_type == "recall_candidates":
                    result = _run_recall_candidates(payload, logs)
                elif task_type == "summarize_index":
                    result = _run_summarize_index(payload, logs)
                else:
                    result = make_error(task_type, f"unsupported task_type: {task_type}", logs)
            except Exception as exc:
                result = make_error(task_type, str(exc), logs)

    append_log(run_log_dir, "file_index_agent.log", {"question_id": payload.get("question_id"), "task_type": task_type, "status": result.get("status"), "summary": result.get("summary"), "reason": result.get("reason")})
    append_log(run_log_dir, "file_index_agent_result.jsonl", result)
    return result


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="File index skill CLI for LLM-WIKI")
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
