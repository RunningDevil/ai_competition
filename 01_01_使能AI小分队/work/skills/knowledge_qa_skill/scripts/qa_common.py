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
