# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from security_common import (
    allow_result,
    append_log,
    deny_result,
    load_permission,
    read_json_file,
    write_json_file,
)
from security_rules import check_question, check_resource


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


SUPPORTED_TASKS = {
    "load_permission",
    "check_question",
    "check_resource",
    "batch_check_resources",
}


def _load_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if args.input_file:
        return read_json_file(args.input_file)
    if args.input_json:
        return json.loads(args.input_json)
    raise ValueError("either --input-json or --input-file is required")


def _permission(payload: Dict[str, Any]) -> Dict[str, Dict[str, List[str]]]:
    return load_permission(payload.get("permission_path"), payload.get("wiki_root") or "llm-wiki")


def _run_load_permission(payload: Dict[str, Any], logs: List[str]) -> Dict[str, Any]:
    permission = _permission(payload)
    summary = {
        "dir": permission.get("dir", {}).get("deny", []),
        "file": permission.get("file", {}).get("deny", []),
        "command": permission.get("command", {}).get("deny", []),
    }
    logs.append("Permission loaded")
    return allow_result("load_permission", reason="permission loaded", logs=logs, extra={"permission": summary})


def _run_check_question(payload: Dict[str, Any], logs: List[str]) -> Dict[str, Any]:
    permission = _permission(payload)
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    ok, reason, matched = check_question(str(payload.get("question_title") or ""), permission, str(wiki_root))
    if not ok:
        logs.append(reason)
        return deny_result("check_question", reason, matched, logs)
    logs.append("Question allowed")
    return allow_result("check_question", logs=logs)


def _run_check_resource(payload: Dict[str, Any], logs: List[str]) -> Dict[str, Any]:
    permission = _permission(payload)
    resource = payload.get("resource") or {}
    ok, reason, matched = check_resource(resource, permission)
    if not ok:
        logs.append(reason)
        return deny_result("check_resource", reason, matched, logs)
    logs.append("Resource allowed")
    return allow_result("check_resource", logs=logs)


def _run_batch_check_resources(payload: Dict[str, Any], logs: List[str]) -> Dict[str, Any]:
    permission = _permission(payload)
    resources = payload.get("resources") or []
    if not isinstance(resources, list):
        return deny_result("batch_check_resources", "resources must be a list", ["input.invalid_resources"], logs)
    checked = []
    for index, resource in enumerate(resources):
        if not isinstance(resource, dict):
            reason = f"resource at index {index} must be object"
            return deny_result("batch_check_resources", reason, ["input.invalid_resource"], logs)
        ok, reason, matched = check_resource(resource, permission)
        checked.append({"index": index, "resource": resource, "decision": "allow" if ok else "deny", "reason": reason, "matched_rules": matched})
        if not ok:
            logs.append(reason)
            return deny_result("batch_check_resources", reason, matched, logs)
    logs.append(f"Batch resources allowed: {len(checked)}")
    return allow_result("batch_check_resources", logs=logs, extra={"checked": checked})


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    task_type = str(payload.get("task_type") or "").strip()
    logs: List[str] = []
    run_log_dir = payload.get("run_log_dir")
    if task_type not in SUPPORTED_TASKS:
        result = deny_result(task_type or "unknown", f"unsupported task_type: {task_type}", ["input.unsupported_task"], logs, status="error")
    elif task_type == "load_permission":
        result = _run_load_permission(payload, logs)
    elif task_type == "check_question":
        result = _run_check_question(payload, logs)
    elif task_type == "check_resource":
        result = _run_check_resource(payload, logs)
    elif task_type == "batch_check_resources":
        result = _run_batch_check_resources(payload, logs)
    else:
        result = deny_result(task_type, f"unsupported task_type: {task_type}", ["input.unsupported_task"], logs, status="error")

    append_log(run_log_dir, "security_guard_agent.log", {"question_id": payload.get("question_id"), "task_type": task_type, "decision": result.get("decision"), "reason": result.get("reason")})
    append_log(run_log_dir, "security_guard_agent_result.jsonl", result)
    return result


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Security guard skill CLI for LLM-WIKI")
    parser.add_argument("--input-json", help="JSON payload string")
    parser.add_argument("--input-file", help="Path to JSON payload file")
    parser.add_argument("--output-file", help="Optional path to write JSON result")
    args = parser.parse_args(argv)

    try:
        payload = _load_payload(args)
        result = run(payload)
    except Exception as exc:
        result = deny_result("unknown", str(exc), ["runtime.exception"], [], status="error")

    if args.output_file:
        write_json_file(args.output_file, result)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
