from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import excel_processor
import ppt_processor
import word_processor
from office_common import (
    append_log,
    comments_to_answer,
    ensure_resource_checked,
    filter_comments,
    fixed_relative_path,
    get_extension,
    is_office_file,
    make_base_result,
    make_error,
    read_json_file,
    resolve_candidate_path,
    source_relative_to_docs,
    write_complex_repair_task,
    write_json_file,
)


try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


WORD_EXTS = {".doc", ".docx"}
PPT_EXTS = {".ppt", ".pptx"}
EXCEL_EXTS = {".xls", ".xlsx"}
SUPPORTED_TASKS = {
    "extract_text",
    "extract_comments",
    "filter_comments",
    "count_comments",
    "fix_comments",
    "excel_analyze",
    "provide_qa_context",
}


def _load_payload(args: argparse.Namespace) -> Dict[str, Any]:
    if args.input_file:
        return read_json_file(args.input_file)
    if args.input_json:
        return json.loads(args.input_json)
    raise ValueError("either --input-json or --input-file is required")


def _processor_for(ext: str):
    if ext in WORD_EXTS:
        return word_processor
    if ext in PPT_EXTS:
        return ppt_processor
    if ext in EXCEL_EXTS:
        return excel_processor
    return None


def _filter_extensions(payload: Dict[str, Any]) -> set[str]:
    filters = payload.get("filters") or {}
    raw = filters.get("extensions") or []
    if isinstance(raw, str):
        raw = [raw]
    if filters.get("extension"):
        raw = list(raw) + [filters.get("extension")]
    return {str(item).lower().lstrip(".") for item in raw if str(item or "").strip()}


def _filter_path_scopes(payload: Dict[str, Any]) -> List[str]:
    filters = payload.get("filters") or {}
    raw = filters.get("path_scopes") or []
    if isinstance(raw, str):
        raw = [raw]
    if filters.get("path_scope"):
        raw = list(raw) + [filters.get("path_scope")]
    result: List[str] = []
    for item in raw:
        text = str(item or "").replace("\\", "/").strip("/")
        if text and text not in result:
            result.append(text)
    return result


def _candidate_allowed(path: Path, payload: Dict[str, Any]) -> bool:
    allowed_exts = _filter_extensions(payload)
    ext = get_extension(path).lstrip(".")
    if allowed_exts and ext not in allowed_exts:
        return False
    scopes = _filter_path_scopes(payload)
    if scopes:
        source_rel = source_relative_to_docs(path, payload.get("wiki_root") or "llm-wiki").strip("/")
        if not any(source_rel == scope or source_rel.startswith(scope.rstrip("/") + "/") for scope in scopes):
            return False
    return True


def _collect_candidates(payload: Dict[str, Any], logs: List[str]) -> List[Path]:
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    paths: List[Path] = []
    for candidate in payload.get("candidate_files") or []:
        path = resolve_candidate_path(candidate, wiki_root)
        if not is_office_file(path):
            logs.append(f"Skipped non-office candidate: {path}")
            continue
        if not path.exists():
            logs.append(f"Candidate does not exist: {path}")
            continue
        if not _candidate_allowed(path, payload):
            logs.append(f"Skipped candidate by filters: {path}")
            continue
        paths.append(path)
    return paths


def _extract_texts(payload: Dict[str, Any], candidate_paths: List[Path], logs: List[str]) -> List[Dict[str, Any]]:
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    texts: List[Dict[str, Any]] = []
    for path in candidate_paths:
        processor = _processor_for(get_extension(path))
        if not processor:
            continue
        try:
            texts.extend(processor.extract_text(path, wiki_root, logs))
        except Exception as exc:
            logs.append(f"Text extraction failed for {path}: {exc}")
    return texts


def _extract_comments(payload: Dict[str, Any], candidate_paths: List[Path], logs: List[str]) -> List[Dict[str, Any]]:
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    comments: List[Dict[str, Any]] = []
    for path in candidate_paths:
        processor = _processor_for(get_extension(path))
        if not processor:
            continue
        try:
            comments.extend(processor.extract_comments(path, wiki_root, logs))
        except Exception as exc:
            logs.append(f"Comment extraction failed for {path}: {exc}")
    return comments


def _fix_comments(payload: Dict[str, Any], candidate_paths: List[Path], logs: List[str]) -> Dict[str, Any]:
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    filters = payload.get("filters") or {}
    complex_tasks: List[str] = []
    for path in candidate_paths:
        processor = _processor_for(get_extension(path))
        if not processor:
            continue
        try:
            result = processor.conservative_fix(path, wiki_root, logs, filters)
            if result.get("status") == "ok":
                return result
            logs.extend(result.get("logs") or [])
            comments = processor.extract_comments(path, wiki_root, logs)
            if filters:
                comments = filter_comments(comments, filters)
            if comments and get_extension(path) in {".docx", ".pptx", ".xlsx"}:
                try:
                    texts = processor.extract_text(path, wiki_root, logs)
                except Exception as exc:
                    logs.append(f"Complex repair context extraction failed for {path}: {exc}")
                    texts = []
                source_rel = source_relative_to_docs(path, wiki_root)
                target_rel = fixed_relative_path(source_rel)
                task_path = write_complex_repair_task(
                    payload,
                    path,
                    source_rel,
                    target_rel,
                    get_extension(path).lstrip("."),
                    comments,
                    texts,
                    str(result.get("error_msg") or result.get("reason") or "deterministic office repair failed"),
                    logs,
                )
                if task_path:
                    complex_tasks.append(task_path)
        except Exception as exc:
            logs.append(f"Fix failed for {path}: {exc}")
    result = make_error("fix_comments", "No office file could be reliably fixed", logs)
    if complex_tasks:
        result["status"] = "complex_repair_required"
        result["complex_repair_tasks"] = complex_tasks
        result["error_msg"] = "复杂批注修复需要由外层 CodeAgent 按 INSTRUCTION.md 执行模型兜底"
    return result


def _excel_analyze(payload: Dict[str, Any], candidate_paths: List[Path], logs: List[str]) -> Dict[str, Any]:
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    for path in candidate_paths:
        if get_extension(path) not in EXCEL_EXTS:
            continue
        try:
            return excel_processor.analyze(path, wiki_root, logs, payload)
        except Exception as exc:
            logs.append(f"Excel analysis failed for {path}: {exc}")
    return make_error("excel_analyze", "No Excel file could be analyzed", logs)


def run(payload: Dict[str, Any]) -> Dict[str, Any]:
    task_type = str(payload.get("task_type") or "").strip()
    logs: List[str] = []
    run_log_dir = payload.get("run_log_dir")
    if task_type not in SUPPORTED_TASKS:
        return make_error(task_type or "unknown", f"unsupported task_type: {task_type}", logs)
    ok, error = ensure_resource_checked(payload)
    if not ok:
        return make_error(task_type, error or "resource safety check failed", logs)
    candidate_paths = _collect_candidates(payload, logs)
    if not candidate_paths:
        return make_error(task_type, "no valid office candidate files", logs)

    if task_type in {"extract_text", "provide_qa_context"}:
        result = make_base_result(task_type)
        result["texts"] = _extract_texts(payload, candidate_paths, logs)
        result["comments"] = _extract_comments(payload, candidate_paths, logs) if task_type == "provide_qa_context" else []
        result["answer"] = {"datas": [item["text"] for item in result["texts"]]}
    elif task_type in {"extract_comments", "filter_comments"}:
        comments = _extract_comments(payload, candidate_paths, logs)
        if task_type == "filter_comments":
            comments = filter_comments(comments, payload.get("filters") or {})
        result = make_base_result(task_type)
        result["comments"] = comments
        result["answer"] = comments_to_answer(comments)
    elif task_type == "count_comments":
        comments = _extract_comments(payload, candidate_paths, logs)
        comments = filter_comments(comments, payload.get("filters") or {}) if payload.get("filters") else comments
        result = make_base_result(task_type)
        result["comments"] = comments
        result["answer"] = {"count": len(comments)}
    elif task_type == "fix_comments":
        result = _fix_comments(payload, candidate_paths, logs)
    elif task_type == "excel_analyze":
        result = _excel_analyze(payload, candidate_paths, logs)
    else:
        result = make_error(task_type, f"unsupported task_type: {task_type}", logs)

    result["logs"] = list(dict.fromkeys((result.get("logs") or []) + logs))
    append_log(run_log_dir, "office_document_agent.log", {"question_id": payload.get("question_id"), "task_type": task_type, "status": result.get("status"), "logs": result.get("logs")})
    append_log(run_log_dir, "office_document_agent_result.jsonl", result)
    return result


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Office document skill CLI for LLM-WIKI")
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
