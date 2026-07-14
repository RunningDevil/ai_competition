from __future__ import annotations

import re
from typing import Any, Dict, Optional


FIELD_PATTERN = re.compile(
    r"(?P<key>todo|to|end[_\-\s]*date)\s*[:：]\s*(?P<value>.*?)(?=(?:[?？,，;；\n\r]\s*(?:todo|to|end[_\-\s]*date)\s*[:：])|$)",
    re.IGNORECASE | re.DOTALL,
)


def _normalize_comment_body(raw: str) -> str:
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    lower = text.casefold()
    if "threaded comment" in lower or "your version of excel allows you to read this threaded comment" in lower:
        match = re.search(r"(?is)(?:^|\n)\s*comment\s*:\s*(?P<body>.*)$", text)
        if match:
            text = match.group("body").strip()
        else:
            text = re.sub(r"(?is)^\s*\[?\s*threaded comment\s*\]?\s*", "", text).strip()
            text = re.sub(r"(?is)^your version of excel allows you to read this threaded comment.*?(?:\n\s*\n|$)", "", text).strip()
            text = re.sub(r"(?is)^learn more:\s*\S+\s*", "", text).strip()
    else:
        threaded_parts = re.split(r"(?im)^\s*comment\s*:\s*", text)
        if len(threaded_parts) > 1:
            text = threaded_parts[-1].strip()
    return text.replace("\u3000", " ")


def _clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ?？,，;；\n\r\t")


def parse_comment_text(raw_text: str, source: str, file_type: str, location: str) -> Dict[str, Any]:
    raw = _normalize_comment_body(str(raw_text or ""))
    parse_body = raw
    fields: Dict[str, str] = {}
    for match in FIELD_PATTERN.finditer(parse_body):
        key = match.group("key").lower().replace("-", "_").replace(" ", "_")
        if key.startswith("end"):
            key = "end_date"
        fields[key] = _clean_value(match.group("value"))
    structured = all(fields.get(key) for key in ("todo", "to", "end_date"))
    return {
        "source": source,
        "file_type": file_type,
        "location": location,
        "raw_text": raw,
        "structured": structured,
        "todo": fields.get("todo"),
        "to": fields.get("to"),
        "end_date": fields.get("end_date"),
    }


def make_free_comment(raw_text: str, source: str, file_type: str, location: str) -> Dict[str, Any]:
    return parse_comment_text(raw_text, source, file_type, location)


def looks_like_comment(raw_text: Optional[str]) -> bool:
    if not raw_text:
        return False
    text = raw_text.strip()
    lowered = text.lower()
    return "todo" in lowered or "待" in text or "需要" in text or "应该" in text or "优化" in text or "调整" in text
