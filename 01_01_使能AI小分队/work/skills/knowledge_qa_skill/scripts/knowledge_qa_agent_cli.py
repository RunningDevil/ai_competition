# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from answer_builder import build_answer
from context_normalizer import normalize_context
from qa_common import (
    SUPPORTED_TASKS,
    append_log,
    ensure_resource_checked,
    make_error,
    read_json_file,
    write_json_file,
)
from query_analyzer import analyze_query
from retriever import retrieve_evidence


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def _load_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if args.input_file:
        return read_json_file(args.input_file)
    if args.input_json:
        return json.loads(args.input_json)
    raise ValueError("either --input-json or --input-file is required")


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
                query = analyze_query(payload)
                blocks = normalize_context(payload, logs)
                if not blocks:
                    result = make_error(task_type, "no context blocks provided", logs)
                else:
                    limit = int((payload.get("filters") or {}).get("limit") or payload.get("top_k") or 8)
                    evidence = retrieve_evidence(blocks, query, limit=max(1, min(limit, 20)))
                    result = build_answer(payload, query, evidence, logs)
                    result["query"] = query
                    result["context_block_count"] = len(blocks)
            except Exception as exc:
                result = make_error(task_type, str(exc), logs)

    append_log(
        run_log_dir,
        "knowledge_qa_agent.log",
        {
            "question_id": payload.get("question_id"),
            "task_type": task_type,
            "status": result.get("status"),
            "confidence": result.get("confidence"),
            "reason": result.get("reason"),
            "logs": result.get("logs"),
        },
    )
    append_log(run_log_dir, "knowledge_qa_agent_result.jsonl", result)
    return result


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Knowledge QA skill CLI for LLM-WIKI")
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
