# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


OFFICE_EXTS = {"doc", "docx", "ppt", "pptx", "xls", "xlsx"}
TEXT_CODE_EXTS = {"md", "html", "xml", "java", "py", "js"}
COUNTABLE_EXTS = OFFICE_EXTS | TEXT_CODE_EXTS
HIGH_RISK_ANSWER = {"error_msg": "高危命令，拒绝访问"}


def read_json_file(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json_file(path: str | Path, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_jsonl(path: str | Path, entry: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "entry": entry,
    }
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_path_text(value: Any) -> str:
    text = normalize_text(value).replace("\\", "/")
    text = re.sub(r"/+", "/", text)
    return text.strip()


def unique_preserve_order(values: Iterable[Any]) -> List[Any]:
    seen = set()
    result = []
    for value in values:
        marker = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
        if marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_dir(path: str | Path) -> Path:
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def script_project_root() -> Path:
    # scripts/main.py -> scripts -> main_orchestrator_skill -> skills -> work -> project root
    return Path(__file__).resolve().parents[4]


def resolve_project_root(project_root: str | Path | None = None) -> Path:
    if project_root:
        return Path(project_root).resolve()
    cwd = Path.cwd().resolve()
    if (cwd / "work" / "skills").exists():
        return cwd
    return script_project_root()


def resolve_maybe_relative(path: str | Path, project_root: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    direct = (Path.cwd() / candidate).resolve()
    if direct.exists():
        return direct
    root_relative = (project_root / candidate).resolve()
    if root_relative.exists():
        return root_relative
    parent_relative = (project_root.parent / candidate).resolve()
    if parent_relative.exists():
        return parent_relative
    return root_relative


def resolve_wiki_root(project_root: Path, wiki_root: str | Path | None = None) -> Path:
    if wiki_root:
        return resolve_maybe_relative(wiki_root, project_root)
    candidates = [
        project_root / "llm-wiki",
        project_root.parent / "llm-wiki",
        project_root.parent / "01_llm_wiki",
        Path("/app/code/judge-assets/01_01_llm_wiki"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return (project_root / "llm-wiki").resolve()


def path_for_payload(path: str | Path, base: Path | None = None) -> str:
    value = Path(path)
    if base:
        try:
            return normalize_path_text(str(value.resolve().relative_to(base.resolve())))
        except ValueError:
            pass
    return normalize_path_text(str(value))


def candidate_path(candidate: Any) -> str:
    if isinstance(candidate, dict):
        return normalize_path_text(candidate.get("path") or candidate.get("relative_path") or candidate.get("source") or candidate.get("absolute_path"))
    return normalize_path_text(candidate)


def candidate_extension(candidate: Any) -> str:
    if isinstance(candidate, dict):
        value = candidate.get("extension") or candidate.get("file_type")
        if value:
            return str(value).lower().lstrip(".")
    return Path(candidate_path(candidate)).suffix.lower().lstrip(".")


def split_candidates(candidates: Iterable[Any]) -> Dict[str, List[Dict[str, Any]]]:
    result = {"office": [], "text_code": [], "other": []}
    for item in candidates or []:
        path = candidate_path(item)
        if not path:
            continue
        ext = candidate_extension(item)
        normalized = dict(item) if isinstance(item, dict) else {"path": path}
        normalized.setdefault("path", path)
        normalized.setdefault("extension", ext)
        if ext in OFFICE_EXTS:
            result["office"].append(normalized)
        elif ext in TEXT_CODE_EXTS:
            result["text_code"].append(normalized)
        else:
            result["other"].append(normalized)
    return result


def make_question_log(question_id: str, message: str, **extra: Any) -> Dict[str, Any]:
    payload = {"question_id": question_id, "message": message}
    payload.update(extra)
    return payload
