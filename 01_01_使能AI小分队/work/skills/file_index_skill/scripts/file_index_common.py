# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


COUNTABLE_EXTS = {"doc", "docx", "ppt", "pptx", "xls", "xlsx", "xml", "java", "py", "html", "md", "js"}
OFFICE_EXTS = {"doc", "docx", "ppt", "pptx", "xls", "xlsx"}
TEXT_CODE_EXTS = {"xml", "java", "py", "html", "md", "js"}


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
    return str(value or "").strip()


def normalize_path_text(value: Any) -> str:
    text = normalize_text(value).replace("\\", "/")
    text = re.sub(r"/+", "/", text)
    return text.strip()


def lower_text(value: Any) -> str:
    return normalize_text(value).casefold()


def lower_path(value: Any) -> str:
    return normalize_path_text(value).casefold()


def classify_extension(extension: str) -> str:
    ext = extension.lower().lstrip(".")
    if ext in OFFICE_EXTS:
        return "office"
    if ext in TEXT_CODE_EXTS:
        return "text_code"
    return "other"


def is_countable_extension(extension: str) -> bool:
    return extension.lower().lstrip(".") in COUNTABLE_EXTS


def resolve_docs_root(payload: Dict[str, Any]) -> Path:
    docs_root = payload.get("docs_root")
    if docs_root:
        return Path(str(docs_root))
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    return Path(str(wiki_root)) / "docs"


def ensure_resource_checked(payload: Dict[str, Any]) -> Tuple[bool, str]:
    safety = payload.get("safety") or {}
    if safety.get("resource_checked") is True:
        return True, ""
    return False, "resource safety check required before indexing docs"


def make_base_result(task_type: str) -> Dict[str, Any]:
    return {
        "status": "ok",
        "task_type": task_type,
        "answer": {},
        "summary": {},
        "files": [],
        "candidate_files": [],
        "logs": [],
    }


def make_error(task_type: str, reason: str, logs: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "status": "error",
        "task_type": task_type,
        "answer": {"datas": []},
        "reason": reason,
        "logs": logs or [],
    }


def unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def filters_include_temp(payload: Dict[str, Any]) -> bool:
    filters = payload.get("filters") or {}
    return filters.get("include_temp_files", True) is not False


def filter_extensions(payload: Dict[str, Any]) -> List[str]:
    filters = payload.get("filters") or {}
    raw = filters.get("extensions") or []
    if isinstance(raw, str):
        raw = [raw]
    return [str(item).lower().lstrip(".") for item in raw if str(item).strip()]


def filter_categories(payload: Dict[str, Any]) -> List[str]:
    filters = payload.get("filters") or {}
    raw = filters.get("categories") or []
    if isinstance(raw, str):
        raw = [raw]
    return [normalize_text(item) for item in raw if normalize_text(item)]


def filter_limit(payload: Dict[str, Any], default: int = 20) -> int:
    filters = payload.get("filters") or {}
    try:
        value = int(filters.get("limit", default))
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, 200))


def apply_metadata_filters(files: List[Dict[str, Any]], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    include_temp = filters_include_temp(payload)
    extensions = set(filter_extensions(payload))
    categories = set(filter_categories(payload))
    result = []
    for item in files:
        if not include_temp and item.get("is_temp"):
            continue
        if extensions and item.get("extension") not in extensions:
            continue
        if categories and item.get("category_dir") not in categories:
            continue
        result.append(item)
    return result


def count_by_extension(files: List[Dict[str, Any]], countable_only: bool = True) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in files:
        ext = str(item.get("extension") or "")
        if not ext:
            continue
        if countable_only and ext not in COUNTABLE_EXTS:
            continue
        counts[ext] = counts.get(ext, 0) + 1
    return dict(sorted(counts.items()))


def count_by_category(files: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in files:
        category = str(item.get("category_dir") or "")
        counts[category] = counts.get(category, 0) + 1
    return dict(sorted(counts.items()))
