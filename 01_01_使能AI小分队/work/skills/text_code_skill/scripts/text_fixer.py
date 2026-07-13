# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from text_code_common import output_fixed_path, rel_to_docs
from text_reader import read_text_file


REPLACE_PATTERNS = [
    re.compile(r"把(.+?)改成(.+)$"),
    re.compile(r"将(.+?)替换为(.+)$"),
]


def _replacement_from_todo(todo_text: str) -> tuple[str, str] | None:
    text = (todo_text or "").strip(" 。.；;")
    for pattern in REPLACE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1).strip(" `\"'"), match.group(2).strip(" `\"'")
    return None


def _replace_first_safe_line(text: str, old: str, new: str) -> tuple[str, bool]:
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if old not in line:
            continue
        if "todo" in stripped.casefold():
            continue
        if stripped.startswith(("#", "//", "/*", "*", "<!--")):
            continue
        lines[index] = line.replace(old, new, 1)
        return "".join(lines), True
    return text, False


def conservative_fix(path: str | Path, wiki_root: str | Path, fixed_root: str | Path | None, todos: List[Dict[str, Any]], logs: List[str]) -> Dict[str, Any]:
    source = Path(path)
    text, encoding = read_text_file(source, logs)
    changed = text
    applied = []
    for todo in todos:
        if not todo.get("structured"):
            continue
        replacement = _replacement_from_todo(str(todo.get("todo") or ""))
        if not replacement:
            continue
        old, new = replacement
        if old and old in changed:
            changed, did_change = _replace_first_safe_line(changed, old, new)
            if not did_change:
                continue
            applied.append({"old": old, "new": new, "location": todo.get("location")})
    if not applied or changed == text:
        return {
            "status": "error",
            "task_type": "fix_todos",
            "answer": {"datas": []},
            "reason": "No text/code TODO could be reliably fixed",
            "logs": logs,
        }

    target, target_rel = output_fixed_path(source, wiki_root, fixed_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(changed, encoding="utf-8")
    source_rel = rel_to_docs(source, wiki_root)
    return {
        "status": "ok",
        "task_type": "fix_todos",
        "answer": {"source": source_rel, "target": target_rel},
        "fixed_files": [target_rel],
        "applied_fixes": applied,
        "logs": logs,
    }
