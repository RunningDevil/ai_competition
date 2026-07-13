# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from file_index_common import (
    append_log,
    classify_extension,
    count_by_category,
    count_by_extension,
    is_countable_extension,
    normalize_path_text,
    write_json_file,
    read_json_file,
)


def _metadata_for_file(path: Path, docs_root: Path) -> Dict[str, Any]:
    relative = path.relative_to(docs_root)
    relative_text = normalize_path_text(str(relative))
    parts = relative.parts
    extension = path.suffix.lower().lstrip(".")
    stat = path.stat()
    return {
        "path": "docs/" + relative_text,
        "name": path.name,
        "stem": path.stem,
        "extension": extension,
        "category_dir": parts[0] if parts else "",
        "size": stat.st_size,
        "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "file_type": classify_extension(extension),
        "is_countable": is_countable_extension(extension),
        "is_temp": path.name.startswith("~$"),
    }


def scan_docs(docs_root: str | Path) -> List[Dict[str, Any]]:
    root = Path(docs_root)
    files: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda p: normalize_path_text(str(p)).casefold()):
        if not path.is_file():
            continue
        files.append(_metadata_for_file(path, root))
    return files


def summarize_files(files: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "total_files": len(files),
        "counts": count_by_extension(files, countable_only=True),
        "categories": count_by_category(files),
    }


def build_or_load_index(
    docs_root: str | Path,
    run_log_dir: str | Path | None = None,
    force: bool = False,
    logs: List[str] | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], str]:
    logs = logs if logs is not None else []
    root = Path(docs_root)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"docs_root does not exist: {root}")

    index_path = ""
    root_key = str(root.resolve())
    if run_log_dir:
        index_file = Path(run_log_dir) / "file_index.json"
        index_path = normalize_path_text(str(index_file))
        if index_file.exists() and not force:
            try:
                cached = read_json_file(index_file)
                if cached.get("source_docs_root") == root_key and isinstance(cached.get("files"), list):
                    logs.append(f"Loaded existing file index: {index_path}")
                    return cached["files"], cached.get("summary") or summarize_files(cached["files"]), index_path
            except Exception as exc:
                logs.append(f"Existing file index ignored: {exc}")

    files = scan_docs(root)
    summary = summarize_files(files)
    if run_log_dir:
        payload = {
            "source_docs_root": root_key,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "summary": summary,
            "files": files,
        }
        write_json_file(Path(run_log_dir) / "file_index.json", payload)
        append_log(run_log_dir, "file_index_agent.log", {"event": "build_index", "summary": summary})
        logs.append(f"Built file index: {index_path}")
    else:
        logs.append("Built file index without run_log_dir cache")
    return files, summary, index_path
