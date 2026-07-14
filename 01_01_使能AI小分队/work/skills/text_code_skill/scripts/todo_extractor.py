# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path
from typing import Any, Dict, List

from comment_parser import clean_comment_text, make_todo
from text_code_common import get_extension, rel_to_docs
from text_reader import read_text_file, split_lines


HTML_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)
BLOCK_COMMENT = re.compile(r"/\*(.*?)\*/", re.DOTALL)
TRIPLE_QUOTED_STRING = re.compile(r"(?is)^[rubf]*('''|\"\"\")")
MARKDOWN_TODO_LINE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)?(?:\[[ xX]\]\s+)?(?P<body>todo\b.*)$", re.IGNORECASE)


def _line_location(index: int) -> str:
    return f"line:{index + 1}"


def _block_location(start: int, text: str) -> str:
    line_count = text.count("\n")
    if line_count <= 0:
        return f"line:{start}"
    return f"line:{start}-{start + line_count}"


def _line_number_from_offset(text: str, offset: int) -> int:
    return text[:offset].count("\n") + 1


def _span_location(start_line: int, end_line: int) -> str:
    if start_line >= end_line:
        return f"line:{start_line}"
    return f"line:{start_line}-{end_line}"


def _append_comment(todos: List[Dict[str, Any]], source: str, ext: str, location: str, raw: str) -> None:
    cleaned = clean_comment_text(raw)
    if not cleaned:
        return
    todos.append(make_todo(source, ext, location, cleaned))


def _is_standalone_triple_quoted_string(token: tokenize.TokenInfo) -> bool:
    if token.type != tokenize.STRING:
        return False
    if not TRIPLE_QUOTED_STRING.match(token.string):
        return False
    prefix = token.line[: token.start[1]]
    return prefix.strip() == ""


def _can_start_standalone_string(previous_token: tokenize.TokenInfo | None) -> bool:
    if previous_token is None:
        return True
    return previous_token.type in {tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE}


def _string_token_text(token_text: str) -> str:
    try:
        value = ast.literal_eval(token_text)
        if isinstance(value, str):
            return value
    except Exception:
        pass

    match = TRIPLE_QUOTED_STRING.match(token_text)
    if not match:
        return token_text
    quote = match.group(1)
    start = match.end()
    end = token_text.rfind(quote)
    if end <= start:
        return token_text[start:]
    return token_text[start:end]


def _extract_python_triple_quoted_todos(text: str, source: str, logs: List[str]) -> List[Dict[str, Any]]:
    todos: List[Dict[str, Any]] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(text).readline)
        previous_significant: tokenize.TokenInfo | None = None
        for token in tokens:
            if _is_standalone_triple_quoted_string(token) and _can_start_standalone_string(previous_significant):
                raw = _string_token_text(token.string)
                _append_comment(todos, source, "py", _span_location(token.start[0], token.end[0]), raw)
            if token.type not in {tokenize.COMMENT, tokenize.NL}:
                previous_significant = token
    except tokenize.TokenError as exc:
        logs.append(f"Python triple-quoted TODO scan skipped: {exc}")
    return todos


def extract_todos_from_text(path: str | Path, wiki_root: str | Path, logs: List[str]) -> List[Dict[str, Any]]:
    text, encoding = read_text_file(path, logs)
    ext = get_extension(path)
    source = rel_to_docs(Path(path), wiki_root)
    lines = split_lines(text)
    todos: List[Dict[str, Any]] = []

    if ext == "py":
        todos.extend(_extract_python_triple_quoted_todos(text, source, logs))

    if ext in {"html", "xml", "md"}:
        for match in HTML_COMMENT.finditer(text):
            start_line = _line_number_from_offset(text, match.start())
            _append_comment(todos, source, ext, _block_location(start_line, match.group(0)), match.group(1))

    if ext in {"java", "js"}:
        for match in BLOCK_COMMENT.finditer(text):
            start_line = _line_number_from_offset(text, match.start())
            _append_comment(todos, source, ext, _block_location(start_line, match.group(0)), match.group(1))

    for index, line in enumerate(lines):
        stripped = line.strip()
        raw = ""
        if ext == "py" and stripped.startswith("#"):
            raw = stripped[1:]
        elif ext in {"java", "js"} and stripped.startswith("//"):
            raw = stripped[2:]
        elif ext == "md":
            match = MARKDOWN_TODO_LINE.match(stripped)
            if match:
                raw = match.group("body")
        if raw:
            _append_comment(todos, source, ext, _line_location(index), raw)

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for item in todos:
        key = (item.get("source"), item.get("location"), item.get("raw_text"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
