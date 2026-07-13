# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from comment_parser import clean_comment_text, make_todo
from text_code_common import get_extension, rel_to_docs
from text_reader import read_text_file, split_lines


TODO_HINT = re.compile(r"\bTODO\b|todo\s*[:：]|待办|需要|需|重构|优化|修复", re.IGNORECASE)
HTML_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)
BLOCK_COMMENT = re.compile(r"/\*(.*?)\*/", re.DOTALL)


def _line_location(index: int) -> str:
    return f"line:{index + 1}"


def _block_location(start: int, text: str) -> str:
    line_count = text.count("\n")
    if line_count <= 0:
        return f"line:{start}"
    return f"line:{start}-{start + line_count}"


def _line_number_from_offset(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1


def _append_if_interesting(todos: List[Dict[str, Any]], source: str, ext: str, location: str, raw: str) -> None:
    cleaned = clean_comment_text(raw)
    if not cleaned:
        return
    if TODO_HINT.search(cleaned) or "todo" in cleaned.casefold():
        todos.append(make_todo(source, ext, location, cleaned))


def extract_todos_from_text(path: str | Path, wiki_root: str | Path, logs: List[str]) -> List[Dict[str, Any]]:
    text, encoding = read_text_file(path, logs)
    ext = get_extension(path)
    source = rel_to_docs(Path(path), wiki_root)
    lines = split_lines(text)
    todos: List[Dict[str, Any]] = []

    if ext in {"html", "xml", "md"}:
        for match in HTML_COMMENT.finditer(text):
            start_line = _line_number_from_offset(text, match.start())
            _append_if_interesting(todos, source, ext, _block_location(start_line, match.group(0)), match.group(1))

    if ext in {"java", "js"}:
        for match in BLOCK_COMMENT.finditer(text):
            start_line = _line_number_from_offset(text, match.start())
            _append_if_interesting(todos, source, ext, _block_location(start_line, match.group(0)), match.group(1))

    for index, line in enumerate(lines):
        stripped = line.strip()
        raw = ""
        if ext == "py" and stripped.startswith("#"):
            raw = stripped[1:]
        elif ext in {"java", "js"} and stripped.startswith("//"):
            raw = stripped[2:]
        elif ext == "md" and TODO_HINT.search(stripped):
            raw = stripped
        elif ext in {"html", "xml"} and TODO_HINT.search(stripped) and "<!--" not in stripped:
            raw = stripped
        if raw:
            _append_if_interesting(todos, source, ext, _line_location(index), raw)

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in todos:
        key = (item.get("source"), item.get("location"), item.get("raw_text"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
