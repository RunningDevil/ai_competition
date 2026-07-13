from __future__ import annotations

import re
from typing import Any, Dict, Optional


FIELD_PATTERN = re.compile(
    r"(?P<key>todo|to|end[_\-\s]*date)\s*[:：]\s*(?P<value>.*?)(?=(?:[,，;；]\s*(?:todo|to|end[_\-\s]*date)\s*[:：])|$)",
    re.IGNORECASE | re.DOTALL,
)


def _clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" ,，;；\n\r\t")


def parse_comment_text(raw_text: str, source: str, file_type: str, location: str) -> Dict[str, Any]:
    raw = str(raw_text or "").strip()
    fields: Dict[str, str] = {}
    for match in FIELD_PATTERN.finditer(raw):
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
