# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DENY_ANSWER = {"error_msg": "高危命令，拒绝访问"}


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


def lowercase_path(value: Any) -> str:
    return normalize_path_text(value).lower()


def load_permission(permission_path: str | Path | None, wiki_root: str | Path | None = None) -> Dict[str, Dict[str, List[str]]]:
    if permission_path:
        path = Path(permission_path)
    else:
        path = Path(wiki_root or "llm-wiki") / "Permission.json"
    if not path.exists():
        return {"dir": {"deny": []}, "command": {"deny": []}, "file": {"deny": []}}
    raw = read_json_file(path)
    return {
        "dir": {"deny": [str(item) for item in (raw.get("dir") or {}).get("deny", [])]},
        "command": {"deny": [str(item) for item in (raw.get("command") or {}).get("deny", [])]},
        "file": {"deny": [str(item) for item in (raw.get("file") or {}).get("deny", [])]},
    }


def make_result(
    task_type: str,
    decision: str,
    reason: str = "",
    matched_rules: Optional[List[str]] = None,
    status: str = "ok",
    logs: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "status": status,
        "task_type": task_type,
        "decision": decision,
        "answer": DENY_ANSWER.copy() if decision == "deny" else {},
        "reason": reason,
        "matched_rules": matched_rules or [],
        "logs": logs or [],
    }
    if extra:
        result.update(extra)
    return result


def allow_result(task_type: str, reason: str = "", logs: Optional[List[str]] = None, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return make_result(task_type, "allow", reason=reason, logs=logs, extra=extra)


def deny_result(
    task_type: str,
    reason: str,
    matched_rules: Optional[List[str]] = None,
    logs: Optional[List[str]] = None,
    status: str = "ok",
) -> Dict[str, Any]:
    return make_result(task_type, "deny", reason=reason, matched_rules=matched_rules, logs=logs, status=status)


def unique_list(values: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def extract_docs_paths(text: str) -> List[str]:
    pattern = re.compile(
        r"docs/[^\s,，;；。)）\]】\"'`]+?\."
        r"(?:docx?|pptx?|xlsx?|xml|java|py|html|md|js|env|cmd|txt|json|ya?ml|sh|bash)",
        re.IGNORECASE,
    )
    return unique_list(match.group(0).rstrip(".。；;，,") for match in pattern.finditer(text or ""))


def resolve_docs_path(path_text: str, wiki_root: str | Path) -> Path:
    normalized = normalize_path_text(path_text)
    if normalized.startswith("llm-wiki/"):
        return Path(normalized)
    if normalized.startswith("docs/"):
        return Path(wiki_root) / normalized
    return Path(wiki_root) / "docs" / normalized
