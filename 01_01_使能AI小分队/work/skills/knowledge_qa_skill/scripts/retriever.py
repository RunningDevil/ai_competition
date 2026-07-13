# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from qa_common import preview_text


INTENT_KIND_BOOSTS = {
    "file_content_paths": {"metadata": 14, "text": 8, "index_summary": 4},
    "environment_info": {"text": 12, "metadata": 6, "comment": 2},
    "command_info": {"text": 12, "metadata": 5},
    "excel_summary": {"table": 22, "text": 10, "metadata": 6},
    "code_static_question": {"risk": 20, "todo": 10, "text": 10, "metadata": 5},
    "from_context": {"text": 10, "comment": 8, "todo": 8, "table": 8, "risk": 8, "metadata": 3},
}


def _contains(haystack: str, needle: str) -> bool:
    return bool(needle) and needle.lower() in haystack.lower()


def _keyword_weight(keyword: str) -> float:
    if len(keyword) >= 8:
        return 6.0
    if len(keyword) >= 4:
        return 4.0
    if len(keyword) >= 2:
        return 2.0
    return 0.0


def _score_block(block: Dict[str, Any], query: Dict[str, Any]) -> Tuple[float, List[str]]:
    source = str(block.get("source") or "")
    file_type = str(block.get("file_type") or "").lower().lstrip(".")
    kind = str(block.get("kind") or "text")
    text = str(block.get("text") or "")
    combined = f"{source} {file_type} {kind} {text}"
    score = 0.0
    reasons: List[str] = []

    kind_boost = INTENT_KIND_BOOSTS.get(query.get("intent"), {}).get(kind, 0)
    if kind_boost:
        score += kind_boost
        reasons.append(f"kind:{kind}")

    for file_name in query.get("files") or []:
        if _contains(source, file_name) or _contains(text, file_name):
            score += 38
            reasons.append(f"file:{file_name}")

    for docs_path in query.get("docs_paths") or []:
        if _contains(source, docs_path) or _contains(text, docs_path):
            score += 34
            reasons.append(f"path:{docs_path}")

    for directory in query.get("directories") or []:
        if _contains(source, directory):
            score += 12
            reasons.append(f"dir:{directory}")

    for ext in query.get("extensions") or []:
        if file_type == ext:
            score += 8
            reasons.append(f"ext:{ext}")

    intent = query.get("intent")
    if intent == "environment_info" and ("02_环境信息" in source or "环境" in source):
        score += 18
        reasons.append("env_dir")
    if intent == "command_info" and ("04_常用命令" in source or "命令" in source):
        score += 18
        reasons.append("command_dir")
    if intent == "excel_summary" and file_type in {"xls", "xlsx"}:
        score += 18
        reasons.append("excel_file")
    if intent == "code_static_question" and file_type in {"md", "html", "xml", "java", "py", "js"}:
        score += 10
        reasons.append("code_text_file")

    for ip in query.get("ips") or []:
        if _contains(combined, ip):
            score += 20
            reasons.append(f"ip:{ip}")

    for keyword in query.get("keywords") or []:
        weight = _keyword_weight(str(keyword))
        if weight <= 0:
            continue
        if _contains(text, str(keyword)):
            score += weight
            reasons.append(f"kw_text:{keyword}")
        elif _contains(source, str(keyword)):
            score += weight * 0.8
            reasons.append(f"kw_path:{keyword}")

    return score, reasons


def retrieve_evidence(blocks: List[Dict[str, Any]], query: Dict[str, Any], limit: int = 8) -> List[Dict[str, Any]]:
    scored: List[Dict[str, Any]] = []
    for block in blocks:
        score, reasons = _score_block(block, query)
        if score <= 0:
            continue
        item = dict(block)
        item["score"] = round(score, 3)
        item["match_reasons"] = reasons
        item["preview"] = preview_text(block.get("text"), 260)
        scored.append(item)

    scored.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("source") or ""), str(item.get("location") or "")))
    return scored[:limit]
