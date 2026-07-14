# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any, Dict


FIELD_PATTERNS = {
    "todo": re.compile(r"\btodo\b\s*[:：]\s*(.*?)(?=(?:[?？,，;；\n\r]\s*)?\bto\b\s*[:：]|$)", re.IGNORECASE | re.DOTALL),
    "to": re.compile(r"\bto\b\s*[:：]\s*(.*?)(?=(?:[?？,，;；\n\r]\s*)?\bend_date\b\s*[:：]|$)", re.IGNORECASE | re.DOTALL),
    "end_date": re.compile(r"\bend_date\b\s*[:：]\s*(\d{8})", re.IGNORECASE),
}


def clean_comment_text(text: str) -> str:
    value = (text or "").strip()
    replacements = [
        ("<!--", ""),
        ("-->", ""),
        ("/*", ""),
        ("*/", ""),
        ("//", ""),
        ("#", ""),
    ]
    for old, new in replacements:
        if value.startswith(old):
            value = value[len(old) :]
        if value.endswith(old):
            value = value[: -len(old)]
    return value.strip()


def _clean_field(value: str) -> str:
    return (value or "").strip(" \t\r\n?？,，;；")


def parse_structured_todo(raw_text: str) -> Dict[str, Any]:
    text = clean_comment_text(raw_text)
    fields = {}
    for key, pattern in FIELD_PATTERNS.items():
        match = pattern.search(text)
        fields[key] = _clean_field(match.group(1)) if match else ""
    structured = bool(fields["todo"] and fields["to"] and fields["end_date"])
    return {
        "raw_text": text,
        "structured": structured,
        "todo": fields["todo"] if structured else "",
        "to": fields["to"] if structured else "",
        "end_date": fields["end_date"] if structured else "",
    }


def make_todo(source: str, file_type: str, location: str, raw_text: str) -> Dict[str, Any]:
    parsed = parse_structured_todo(raw_text)
    return {
        "source": source,
        "file_type": file_type,
        "location": location,
        "raw_text": parsed["raw_text"],
        "structured": parsed["structured"],
        "todo": parsed["todo"],
        "to": parsed["to"],
        "end_date": parsed["end_date"],
    }
