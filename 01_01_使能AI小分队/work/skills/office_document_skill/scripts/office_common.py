from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


OFFICE_EXTS = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}
OOXML_EXTS = {".docx", ".pptx", ".xlsx"}
LEGACY_EXTS = {".doc", ".ppt", ".xls"}
LEGACY_TARGET_EXT = {".doc": ".docx", ".ppt": ".pptx", ".xls": ".xlsx"}
LEGACY_CONVERT_FORMAT = {".doc": "docx", ".ppt": "pptx", ".xls": "xlsx"}
REPLACEMENT_RE = re.compile(
    r"[\"“”'‘’]?(?P<old>.+?)[\"“”'‘’]?\s*(?:修改为|改为|替换为|换成|改成)\s*"
    r"[\"“”'‘’]?(?P<new>.+?)[\"“”'‘’]?(?:$|[,，;；。])"
)


def normalize_path_text(value: str) -> str:
    return str(value).replace("\\", "/")


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


def _trim_blocks(blocks: Iterable[Dict[str, Any]], limit: int = 40) -> List[Dict[str, Any]]:
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


def make_base_result(task_type: str, status: str = "ok") -> Dict[str, Any]:
    return {
        "status": status,
        "task_type": task_type,
        "texts": [],
        "comments": [],
        "answer": {},
        "fixed_files": [],
        "logs": [],
    }


def make_error(task_type: str, message: str, logs: Optional[List[str]] = None) -> Dict[str, Any]:
    result = make_base_result(task_type, "error")
    result["error_msg"] = message
    result["answer"] = {"datas": []}
    result["logs"] = logs or []
    return result


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


def get_extension(path: str | Path) -> str:
    return Path(str(path)).suffix.lower()


def is_office_file(path: str | Path) -> bool:
    return get_extension(path) in OFFICE_EXTS


def is_legacy_office(path: str | Path) -> bool:
    return get_extension(path) in LEGACY_EXTS


def ensure_resource_checked(payload: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    safety = payload.get("safety") or {}
    if safety.get("resource_checked") is True:
        return True, None
    return False, "resource safety check is required before office document file access"


def resolve_candidate_path(candidate: Dict[str, Any], wiki_root: str | Path) -> Path:
    absolute_path = candidate.get("absolute_path")
    if absolute_path:
        return Path(absolute_path)
    raw_path = candidate.get("path") or candidate.get("source") or ""
    path = Path(raw_path)
    if path.is_absolute():
        return path
    wiki_root_path = Path(wiki_root)
    if normalize_path_text(raw_path).startswith("docs/"):
        return wiki_root_path / raw_path
    return wiki_root_path / "docs" / raw_path


def source_relative_to_docs(source_path: str | Path, wiki_root: str | Path) -> str:
    source = Path(source_path)
    wiki = Path(wiki_root)
    docs = wiki / "docs"
    try:
        return normalize_path_text("docs/" + str(source.resolve().relative_to(docs.resolve())))
    except Exception:
        raw = normalize_path_text(str(source))
        marker = "/docs/"
        if marker in raw:
            return "docs/" + raw.split(marker, 1)[1]
        if raw.startswith("docs/"):
            return raw
        return normalize_path_text(source.name)


def fixed_relative_path(source_rel: str) -> str:
    normalized = normalize_path_text(source_rel)
    if normalized.startswith("docs/"):
        return "output/fixed/" + normalized[len("docs/") :]
    return "output/fixed/" + normalized.lstrip("/")


def fixed_absolute_path(source_rel: str, wiki_root: str | Path) -> Path:
    rel = fixed_relative_path(source_rel)
    return Path(wiki_root) / rel


def copy_to_fixed(source_path: str | Path, wiki_root: str | Path) -> Tuple[str, Path]:
    source_rel = source_relative_to_docs(source_path, wiki_root)
    target_rel = fixed_relative_path(source_rel)
    target_abs = Path(wiki_root) / target_rel
    target_abs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_abs)
    return target_rel, target_abs


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
        "agent_family": "office_document",
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


def _clean_replacement_part(value: str) -> str:
    cleaned = str(value or "").strip().strip("\"“”'‘’`").strip(" ，,；;。:")
    cleaned = re.sub(r"(?i)^todo\s*[:：]\s*", "", cleaned).strip()
    if cleaned.startswith(("把", "将")) and len(cleaned) > 1:
        cleaned = cleaned[1:].strip()
    return cleaned.strip().strip("\"“”'‘’`").strip()


def replacement_from_comment(comment: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    for key in ("todo", "raw_text"):
        text = str(comment.get(key) or "")
        match = REPLACEMENT_RE.search(text)
        if not match:
            continue
        old = _clean_replacement_part(match.group("old"))
        new = _clean_replacement_part(match.group("new"))
        if old and new and old != new:
            return old, new
    return None


def find_office_converter() -> Optional[str]:
    return shutil.which("soffice") or shutil.which("libreoffice")


def _install_commands() -> List[List[str]]:
    if platform.system().lower() != "linux":
        return []
    commands: List[List[str]] = []
    if shutil.which("apt-get"):
        commands.append(["apt-get", "update"])
        commands.append(["apt-get", "install", "-y", "libreoffice"])
    elif shutil.which("dnf"):
        commands.append(["dnf", "install", "-y", "libreoffice"])
    elif shutil.which("yum"):
        commands.append(["yum", "install", "-y", "libreoffice"])
    elif shutil.which("apk"):
        commands.append(["apk", "add", "--no-cache", "libreoffice"])
    return commands


def attempt_install_libreoffice(max_retries: int = 2, logs: Optional[List[str]] = None) -> Optional[str]:
    logs = logs if logs is not None else []
    if os.environ.get("OFFICE_DISABLE_LIBREOFFICE_INSTALL") == "1":
        logs.append("LibreOffice install skipped by OFFICE_DISABLE_LIBREOFFICE_INSTALL=1")
        return None
    commands = _install_commands()
    if not commands:
        logs.append("No supported package manager found for LibreOffice install")
        return None
    timeout = int(os.environ.get("OFFICE_INSTALL_TIMEOUT_SECONDS", "600"))
    for attempt in range(1, max_retries + 1):
        logs.append(f"LibreOffice install attempt {attempt}/{max_retries}")
        all_ok = True
        for command in commands:
            try:
                completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)
                if completed.returncode != 0:
                    all_ok = False
                    logs.append(f"Command failed: {' '.join(command)} rc={completed.returncode} stderr={completed.stderr[-500:]}")
                    break
            except Exception as exc:
                all_ok = False
                logs.append(f"Command error: {' '.join(command)} error={exc}")
                break
        converter = find_office_converter()
        if all_ok and converter:
            logs.append(f"LibreOffice available after install: {converter}")
            return converter
    return find_office_converter()


def convert_legacy_office(source_path: str | Path, logs: Optional[List[str]] = None) -> Optional[Path]:
    logs = logs if logs is not None else []
    source = Path(source_path)
    ext = source.suffix.lower()
    if ext not in LEGACY_EXTS:
        return source
    converter = find_office_converter()
    if not converter:
        converter = attempt_install_libreoffice(max_retries=2, logs=logs)
    if not converter:
        logs.append("No soffice/libreoffice converter available; falling back")
        return None
    target_format = LEGACY_CONVERT_FORMAT[ext]
    out_dir = Path(tempfile.mkdtemp(prefix="office_convert_"))
    command = [converter, "--headless", "--convert-to", target_format, "--outdir", str(out_dir), str(source)]
    try:
        completed = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
    except Exception as exc:
        logs.append(f"LibreOffice conversion failed to run: {exc}")
        return None
    if completed.returncode != 0:
        logs.append(f"LibreOffice conversion failed rc={completed.returncode} stderr={completed.stderr[-500:]}")
        return None
    expected = out_dir / (source.stem + LEGACY_TARGET_EXT[ext])
    if expected.exists():
        logs.append(f"Converted {source} to {expected}")
        return expected
    converted = list(out_dir.glob(source.stem + ".*"))
    if converted:
        logs.append(f"Converted {source} to {converted[0]}")
        return converted[0]
    logs.append(f"LibreOffice reported success but no converted file found in {out_dir}")
    return None


def extract_printable_text_from_binary(source_path: str | Path, max_chars: int = 200000) -> str:
    data = Path(source_path).read_bytes()
    chunks: List[str] = []
    for encoding in ("utf-8", "gb18030", "utf-16le", "latin-1"):
        try:
            text = data.decode(encoding, errors="ignore")
        except Exception:
            continue
        parts = re.findall(r"[\u4e00-\u9fffA-Za-z0-9_，。；：、“”‘’（）()\[\]{}<>/\\:;,.!?@#$%^&*+=|~`\-\s]{4,}", text)
        if parts:
            chunks.extend(part.strip() for part in parts if part.strip())
    seen = set()
    unique: List[str] = []
    for chunk in chunks:
        compact = re.sub(r"\s+", " ", chunk).strip()
        if compact and compact not in seen:
            seen.add(compact)
            unique.append(compact)
    return "\n".join(unique)[:max_chars]


def _normalize_date(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return _normalize_date(value[0]) if value else ""
    text = str(value).strip()
    match = re.search(r"(20\d{6})", text)
    if match:
        return match.group(1)
    digits = re.sub(r"\D", "", text)
    return digits if len(digits) == 8 else ""


def _first_filter_date(filters: Dict[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = filters.get(key)
        date = _normalize_date(value)
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


def filter_comments(comments: Iterable[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    assignee = filters.get("assignee") or filters.get("to")
    exact_date, end_date_gte, end_date_lte, end_date_gt, end_date_lt = _date_bounds(filters)
    has_date_filter = bool(exact_date or end_date_gte or end_date_lte or end_date_gt or end_date_lt)
    file_name = filters.get("file_name") or filters.get("filename")
    raw_exts = filters.get("extensions") or []
    if isinstance(raw_exts, str):
        raw_exts = [raw_exts]
    if filters.get("extension"):
        raw_exts = list(raw_exts) + [filters.get("extension")]
    extensions = {str(ext).lower().lstrip(".") for ext in raw_exts if str(ext or "").strip()}
    result = []
    for comment in comments:
        if (assignee or has_date_filter) and not comment.get("structured"):
            continue
        if assignee and comment.get("to") != assignee:
            continue
        if has_date_filter and not _matches_date_filter(comment.get("end_date"), exact_date, end_date_gte, end_date_lte, end_date_gt, end_date_lt):
            continue
        if file_name and file_name not in str(comment.get("source", "")):
            continue
        if extensions and str(comment.get("file_type") or "").lower().lstrip(".") not in extensions:
            continue
        result.append(comment)
    return result


def comments_to_answer(comments: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return {"datas": [str(comment.get("raw_text", "")) for comment in comments if comment.get("raw_text")]}
