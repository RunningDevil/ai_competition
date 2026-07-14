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


def _safe_name(value: Any) -> str:
    text = str(value or "unknown")
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("_") or "unknown"


def _answer_file_for_question(question_id: Any, wiki_root: str | Path) -> str:
    text = str(question_id or "")
    match = re.match(r"(group-\d+)-\d+$", text)
    group_name = match.group(1) if match else "group-unknown"
    return normalize_path_text(str(Path(wiki_root) / "output" / f"{group_name}-answer.md"))


def _trim_text(value: Any, limit: int = 1200) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _trim_blocks(blocks: Iterable[Dict[str, Any]], limit: int = 60) -> List[Dict[str, Any]]:
    trimmed: List[Dict[str, Any]] = []
    for block in list(blocks)[:limit]:
        if not isinstance(block, dict):
            continue
        item = dict(block)
        if "text" in item:
            item["text"] = _trim_text(item.get("text"))
        if "raw_text" in item:
            item["raw_text"] = _trim_text(item.get("raw_text"))
        trimmed.append(item)
    return trimmed


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


def write_complex_repair_task(
    payload: Dict[str, Any],
    source_path: str | Path,
    source_rel: str,
    target_rel: str,
    file_type: str,
    annotations: Iterable[Dict[str, Any]],
    context_blocks: Iterable[Dict[str, Any]],
    reason: str,
    logs: List[str],
) -> Optional[str]:
    run_log_dir = payload.get("run_log_dir")
    if not run_log_dir:
        logs.append("Complex repair task not written because run_log_dir is missing")
        return None
    task_dir = Path(run_log_dir) / "complex_repair_tasks"
    task_dir.mkdir(parents=True, exist_ok=True)
    question_id = payload.get("question_id") or "unknown"
    source = Path(source_path)
    task_path = task_dir / f"{_safe_name(question_id)}_{_safe_name(source.stem)}_{file_type}.json"
    wiki_root = payload.get("wiki_root") or "llm-wiki"
    task = {
        "status": "pending_model_repair",
        "task_kind": "complex_annotation_repair",
        "agent_family": "text_code",
        "question_id": question_id,
        "question_title": payload.get("question_title"),
        "file_type": file_type,
        "source": normalize_path_text(source_rel),
        "source_abs": normalize_path_text(str(source)),
        "target": normalize_path_text(target_rel),
        "target_abs": normalize_path_text(str(Path(wiki_root) / target_rel)),
        "answer_file": _answer_file_for_question(question_id, wiki_root),
        "filters": payload.get("filters") or {},
        "annotations": _trim_blocks(annotations),
        "context_blocks": _trim_blocks(context_blocks),
        "reason": reason,
        "model_repair_contract": {
            "must_use_model_judgement": True,
            "must_not_modify_source": True,
            "must_write_target": True,
            "must_verify_target_changed": True,
            "must_update_answer_file_on_success": True,
            "answer": {"source": normalize_path_text(source_rel), "target": normalize_path_text(target_rel)},
        },
    }
    write_json_file(task_path, task)
    logs.append(f"Complex repair task written: {task_path}")
    return normalize_path_text(str(task_path))


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


def _normalize_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return _normalize_date(value[0]) if value else ""
    text = normalize_text(value)
    match = re.search(r"(20\d{6})", text)
    if match:
        return match.group(1)
    digits = re.sub(r"\D", "", text)
    return digits if len(digits) == 8 else ""


def _first_filter_date(filters: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        date = _normalize_date(filters.get(key))
        if date:
            return date
    return ""


def _date_bounds(filters: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    exact = _first_filter_date(filters, ("end_date", "date"))
    gte = _first_filter_date(filters, ("end_date_gte", "date_gte", "end_date_min", "date_min", "start_date", "from_date"))
    lte = _first_filter_date(filters, ("end_date_lte", "date_lte", "end_date_max", "date_max", "end_date_before", "date_before", "until_date", "to_date"))
    gt = _first_filter_date(filters, ("end_date_gt", "date_gt", "end_date_after_strict", "date_after_strict"))
    lt = _first_filter_date(filters, ("end_date_lt", "date_lt", "end_date_before_strict", "date_before_strict"))
    date_range = filters.get("end_date_range") or filters.get("date_range")
    if isinstance(date_range, dict):
        gte = gte or _first_filter_date(date_range, ("start", "gte", "from", "min"))
        lte = lte or _first_filter_date(date_range, ("end", "lte", "to", "max"))
    elif isinstance(date_range, (list, tuple)) and len(date_range) >= 2:
        first = _normalize_date(date_range[0])
        second = _normalize_date(date_range[1])
        if first and second:
            if first > second:
                first, second = second, first
            gte = gte or first
            lte = lte or second
    return exact, gte, lte, gt, lt


def _matches_date_filter(item_date: Any, exact: str, gte: str, lte: str, gt: str, lt: str) -> bool:
    date = _normalize_date(item_date)
    if exact and date != exact:
        return False
    if gte and (not date or date < gte):
        return False
    if lte and (not date or date > lte):
        return False
    if gt and (not date or date <= gt):
        return False
    if lt and (not date or date >= lt):
        return False
    return True


def filter_todos(todos: List[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    assignee = normalize_text(filters.get("assignee") or filters.get("to"))
    exact_date, end_date_gte, end_date_lte, end_date_gt, end_date_lt = _date_bounds(filters)
    has_date_filter = bool(exact_date or end_date_gte or end_date_lte or end_date_gt or end_date_lt)
    file_name = normalize_text(filters.get("file_name"))
    extension = normalize_text(filters.get("extension")).lower().lstrip(".")
    raw_exts = filters.get("extensions") or []
    if isinstance(raw_exts, str):
        raw_exts = [raw_exts]
    extensions = {normalize_text(item).lower().lstrip(".") for item in raw_exts if normalize_text(item)}
    if extension:
        extensions.add(extension)
    keyword = normalize_text(filters.get("keyword"))
    structured = filters.get("structured")
    result = []
    for item in todos:
        if (assignee or has_date_filter) and not item.get("structured"):
            continue
        if assignee and assignee != normalize_text(item.get("to")):
            continue
        if has_date_filter and not _matches_date_filter(item.get("end_date"), exact_date, end_date_gte, end_date_lte, end_date_gt, end_date_lt):
            continue
        if file_name and file_name not in normalize_text(item.get("source")):
            continue
        if extensions and normalize_text(item.get("file_type")).lower().lstrip(".") not in extensions:
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
