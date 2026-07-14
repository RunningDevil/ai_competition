# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SUPPORTED_TASKS = {
    "answer_from_context",
    "answer_file_content_paths",
    "answer_environment_info",
    "answer_command_info",
    "answer_excel_summary",
    "answer_code_static_question",
    "provide_answer_draft",
}


TEXT_CODE_EXTS = {"md", "html", "xml", "java", "py", "js"}
OFFICE_EXTS = {"doc", "docx", "ppt", "pptx", "xls", "xlsx"}
COUNTABLE_EXTS = OFFICE_EXTS | TEXT_CODE_EXTS


def read_json_file(path: str | Path) -> Dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json_file(path: str | Path, data: Dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _safe_name(value: Any) -> str:
    text = str(value or "unknown")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "unknown"


def _answer_file_for_question(question_id: Any, wiki_root: str | Path) -> str:
    text = str(question_id or "")
    match = re.match(r"(group-\d+)-\d+$", text)
    group_name = match.group(1) if match else "group-unknown"
    return normalize_path_text(str(Path(wiki_root) / "output" / f"{group_name}-answer.md"))


def _trim_value(value: Any, limit: int = 3000) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _trim_blocks(blocks: Iterable[Dict[str, Any]], limit: int = 20) -> List[Dict[str, Any]]:
    trimmed: List[Dict[str, Any]] = []
    for block in list(blocks)[:limit]:
        if not isinstance(block, dict):
            continue
        item = dict(block)
        if "text" in item:
            item["text"] = _trim_value(item.get("text"))
        if "preview" in item:
            item["preview"] = _trim_value(item.get("preview"), 800)
        trimmed.append(item)
    return trimmed


def _candidate_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for candidate in payload.get("candidate_files") or []:
        if isinstance(candidate, dict):
            record = dict(candidate)
            record["path"] = get_candidate_path(candidate)
        else:
            record = {"path": get_candidate_path(candidate)}
        if record.get("path"):
            records.append(record)
    return records


def write_code_reasoning_task(
    payload: Dict[str, Any],
    query: Dict[str, Any],
    evidence: Iterable[Dict[str, Any]],
    logs: List[str],
) -> Optional[str]:
    run_log_dir = payload.get("run_log_dir")
    if not run_log_dir:
        logs.append("Code reasoning task not written because run_log_dir is missing")
        return None
    task_dir = Path(run_log_dir) / "code_reasoning_tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    question_id = payload.get("question_id") or "unknown"
    task_path = task_dir / f"{_safe_name(question_id)}_code_reasoning.json"
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    task = {
        "status": "pending_model_reasoning",
        "task_kind": "code_execution_result_reasoning",
        "question_id": question_id,
        "question_title": payload.get("question_title"),
        "wiki_root": normalize_path_text(wiki_root),
        "answer_file": _answer_file_for_question(question_id, wiki_root),
        "query": query,
        "candidate_files": _candidate_records(payload),
        "evidence": _trim_blocks(evidence),
        "model_reasoning_contract": {
            "must_use_model_judgement": True,
            "must_not_execute_code": True,
            "must_not_execute_commands": True,
            "must_not_access_network": True,
            "must_update_answer_file_on_success": True,
            "answer_format": {"datas": ["<model inferred execution result>"]},
        },
    }
    write_json_file(task_path, task)
    logs.append(f"Code reasoning task written: {task_path}")
    return normalize_path_text(str(task_path))


def append_log(run_log_dir: str | Path | None, file_name: str, entry: Any) -> None:
    if not run_log_dir:
        return
    log_dir = Path(run_log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / file_name
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "entry": entry,
    }
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def normalize_text(value: Any) -> str:
    text = str(value or "")
    return re.sub(r"\s+", " ", text).strip()


def normalize_path_text(value: Any) -> str:
    text = normalize_text(value).replace("\\", "/")
    text = re.sub(r"/+", "/", text)
    return text.strip()


def get_extension(path: Any) -> str:
    text = normalize_path_text(path)
    suffix = Path(text).suffix.lower().lstrip(".")
    return suffix


def get_candidate_path(candidate: Any) -> str:
    if isinstance(candidate, dict):
        return normalize_path_text(
            candidate.get("path")
            or candidate.get("relative_path")
            or candidate.get("absolute_path")
            or candidate.get("source")
        )
    return normalize_path_text(candidate)


def ensure_resource_checked(payload: Dict[str, Any]) -> Tuple[bool, str]:
    safety = payload.get("safety") or {}
    if safety.get("resource_checked") is True:
        return True, ""
    return False, "resource safety check failed"


def make_base_result(task_type: str) -> Dict[str, Any]:
    return {
        "status": "ok",
        "task_type": task_type,
        "answer": {},
        "evidence": [],
        "confidence": 0.0,
        "logs": [],
    }


def make_error(task_type: str, reason: str, logs: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "status": "error",
        "task_type": task_type or "unknown",
        "answer": {"datas": []},
        "evidence": [],
        "confidence": 0.0,
        "reason": reason,
        "logs": logs or [],
    }


def unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        text = normalize_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def preview_text(text: Any, limit: int = 240) -> str:
    value = normalize_text(text)
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."
