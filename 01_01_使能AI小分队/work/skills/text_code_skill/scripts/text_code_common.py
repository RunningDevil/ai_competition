# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SUPPORTED_EXTS = {"md", "html", "xml", "java", "py", "js"}


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


def get_extension(path: str | Path) -> str:
    return Path(str(path)).suffix.lower().lstrip(".")


def rel_to_docs(path: Path, wiki_root: str | Path) -> str:
    wiki = Path(wiki_root)
    try:
        return normalize_path_text(str(path.relative_to(wiki)))
    except ValueError:
        pass
    docs_root = wiki / "docs"
    try:
        return "docs/" + normalize_path_text(str(path.relative_to(docs_root)))
    except ValueError:
        return normalize_path_text(str(path))


def resolve_candidate_path(candidate: Any, wiki_root: str | Path) -> Path:
    if isinstance(candidate, dict):
        value = candidate.get("absolute_path") or candidate.get("path") or candidate.get("relative_path")
    else:
        value = candidate
    text = normalize_path_text(value)
    if not text:
        return Path("")
    path = Path(text)
    if path.is_absolute():
        return path
    if text.startswith("llm-wiki/"):
        return Path(text)
    if text.startswith("docs/"):
        return Path(wiki_root) / text
    return Path(wiki_root) / "docs" / text


def ensure_resource_checked(payload: Dict[str, Any]) -> Tuple[bool, str]:
    safety = payload.get("safety") or {}
    if safety.get("resource_checked") is True:
        return True, ""
    return False, "resource safety check failed"


def make_base_result(task_type: str) -> Dict[str, Any]:
    return {
        "status": "ok",
        "task_type": task_type,
        "texts": [],
        "todos": [],
        "risks": [],
        "answer": {},
        "fixed_files": [],
        "logs": [],
    }


def make_error(task_type: str, reason: str, logs: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "status": "error",
        "task_type": task_type,
        "reason": reason,
        "answer": {"datas": []},
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


def todo_to_answer_text(todo: Dict[str, Any]) -> str:
    if todo.get("structured"):
        return f"todo: {todo.get('todo', '')},to:{todo.get('to', '')},end_date:{todo.get('end_date', '')}"
    return str(todo.get("raw_text") or "")


def todos_to_answer(todos: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"datas": [todo_to_answer_text(item) for item in todos]}


def filter_todos(todos: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    assignee = normalize_text(filters.get("assignee") or filters.get("to"))
    end_date = normalize_text(filters.get("end_date"))
    file_name = normalize_text(filters.get("file_name"))
    extension = normalize_text(filters.get("extension")).lower().lstrip(".")
    keyword = normalize_text(filters.get("keyword"))
    structured = filters.get("structured")
    result = []
    for item in todos:
        if assignee and assignee != normalize_text(item.get("to")):
            continue
        if end_date and end_date != normalize_text(item.get("end_date")):
            continue
        if file_name and file_name not in normalize_text(item.get("source")):
            continue
        if extension and extension != normalize_text(item.get("file_type")).lower():
            continue
        if structured is not None and bool(item.get("structured")) != bool(structured):
            continue
        if keyword and keyword not in normalize_text(item.get("raw_text")) and keyword not in normalize_text(item.get("todo")):
            continue
        result.append(item)
    return result


def output_fixed_path(source: Path, wiki_root: str | Path, fixed_root: str | Path | None = None) -> Tuple[Path, str]:
    wiki = Path(wiki_root)
    fixed = Path(fixed_root) if fixed_root else wiki / "output" / "fixed"
    docs_root = wiki / "docs"
    try:
        relative = source.relative_to(docs_root)
    except ValueError:
        relative = Path(source.name)
    target = fixed / relative
    target_rel = "output/fixed/" + normalize_path_text(str(relative))
    return target, target_rel


def copy_preserving_text(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
