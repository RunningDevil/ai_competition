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


def filter_comments(comments: Iterable[Dict[str, Any]], filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    assignee = filters.get("assignee") or filters.get("to")
    end_date = filters.get("end_date") or filters.get("date")
    file_name = filters.get("file_name") or filters.get("filename")
    result = []
    for comment in comments:
        if assignee and comment.get("to") != assignee:
            continue
        if end_date and comment.get("end_date") != str(end_date):
            continue
        if file_name and file_name not in str(comment.get("source", "")):
            continue
        result.append(comment)
    return result


def comments_to_answer(comments: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return {"datas": [str(comment.get("raw_text", "")) for comment in comments if comment.get("raw_text")]}
