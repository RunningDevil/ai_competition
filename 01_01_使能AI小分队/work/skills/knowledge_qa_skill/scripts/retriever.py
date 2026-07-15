# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from qa_common import preview_text


COMMAND_SIGNAL_RE = re.compile(
    r"\b(?:ssh|scp|sftp|gsql|psql|mysql|sqlcmd|kubectl|docker(?:-compose)?|curl|wget|python3?|java|mvn|gradle|npm|yarn|pnpm|git|systemctl|journalctl|rm|rmdir|del|remove-item|kill|pkill|taskkill|chmod|chown|bash|sh)\b|命令|指令|命令行|控制台|终端|客户端|连接|登录|清理|停止|重启|权限",
    re.IGNORECASE,
)


INTENT_KIND_BOOSTS = {
    "file_content_paths": {"text": 16, "table": 12, "comment": 8, "todo": 8, "metadata": 3, "index_summary": 2},
    "environment_info": {"text": 12, "metadata": 6, "comment": 2},
    "command_info": {"text": 12, "metadata": 5},
    "excel_summary": {"table": 22, "text": 10, "metadata": 6},
    "code_static_question": {"risk": 20, "todo": 10, "text": 10, "metadata": 5},
    "from_context": {"text": 10, "comment": 8, "todo": 8, "table": 8, "risk": 8, "metadata": 3},
}

CONTENT_PATH_EXCLUDED_SEGMENTS = ("/comment_stat_questions/",)


def _contains(haystack: str, needle: str) -> bool:
    return bool(needle) and needle.lower() in haystack.lower()


def _is_non_business_support_file(source: str, text: str, query: Dict[str, Any]) -> bool:
    if query.get("intent") != "file_content_paths":
        return False
    normalized = source.replace("\\", "/").casefold()
    if any(segment in normalized for segment in CONTENT_PATH_EXCLUDED_SEGMENTS):
        return True
    return False


def _required_phrase_matches(combined: str, query: Dict[str, Any]) -> List[str]:
    phrases = [str(item or "").strip() for item in query.get("required_phrases") or [] if str(item or "").strip()]
    term_groups = query.get("required_phrase_terms") or []
    if not phrases:
        return []
    matches: List[str] = []
    for index, phrase in enumerate(phrases):
        if _contains(combined, phrase):
            matches.append(phrase)
            continue
        terms = []
        if index < len(term_groups) and isinstance(term_groups[index], list):
            terms = [str(item or "").strip() for item in term_groups[index] if str(item or "").strip()]
        if len(terms) >= 2 and all(_contains(combined, term) for term in terms):
            matches.append("+".join(terms))
        elif len(terms) == 1 and len(terms[0]) >= 3 and _contains(combined, terms[0]):
            matches.append(terms[0])
    return matches


def _keyword_weight(keyword: str) -> float:
    if len(keyword) >= 8:
        return 6.0
    if len(keyword) >= 4:
        return 4.0
    if len(keyword) >= 2:
        return 2.0
    return 0.0


def _has_negative_keyword_context(text: str, query: Dict[str, Any]) -> bool:
    compact = "".join(str(text or "").split()).lower()
    if not compact:
        return False
    for keyword in query.get("keywords") or []:
        key = str(keyword or "").strip().lower()
        if len(key) < 2:
            continue
        if key in {"文件", "路径", "名称", "哪些", "业务", "相关", "涉及"}:
            continue
        patterns = (
            f"不涉及{key}",
            f"未涉及{key}",
            f"不包含{key}",
            f"未包含{key}",
            f"没有{key}",
            f"无{key}",
            f"非{key}",
        )
        if any(pattern in compact for pattern in patterns):
            return True
    return False


def _score_block(block: Dict[str, Any], query: Dict[str, Any]) -> Tuple[float, List[str]]:
    source = str(block.get("source") or "")
    file_type = str(block.get("file_type") or "").lower().lstrip(".")
    kind = str(block.get("kind") or "text")
    text = str(block.get("text") or "")
    if _is_non_business_support_file(source, text, query):
        return 0.0, []
    if query.get("intent") == "file_content_paths" and _has_negative_keyword_context(text, query):
        return 0.0, []
    combined = f"{source} {file_type} {kind} {text}"
    score = 0.0
    reasons: List[str] = []

    if query.get("intent") == "file_content_paths" and query.get("required_phrases"):
        matched_required = _required_phrase_matches(combined, query)
        if not matched_required:
            return 0.0, []
        score += 30
        reasons.extend(f"required_phrase:{phrase}" for phrase in matched_required[:3])

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
    if intent == "command_info" and COMMAND_SIGNAL_RE.search(combined):
        score += 10
        reasons.append("command_signal")
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

    evidence_reasons = ("file:", "path:", "dir:", "ip:", "kw_path:", "kw_text:")
    if query.get("intent") == "file_content_paths" and not any(reason.startswith(evidence_reasons) for reason in reasons):
        return 0.0, []

    if query.get("intent") == "command_info" and not any(
        str(reason).startswith(("file:", "path:", "dir:", "kw_text:", "kw_path:", "command_dir", "command_signal")) for reason in reasons
    ):
        return 0.0, []

    if kind == "metadata" and not any(reason.startswith((*evidence_reasons, "ext:")) for reason in reasons):
        return 0.0, []

    return score, reasons


def _unique_reasons(items: List[Dict[str, Any]]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        for reason in item.get("match_reasons") or []:
            if reason in seen:
                continue
            seen.add(reason)
            result.append(reason)
    return result


def _reason_diversity_score(reasons: List[str]) -> float:
    prefixes = {str(reason).split(":", 1)[0] for reason in reasons}
    keyword_hits = {str(reason).split(":", 1)[1] for reason in reasons if str(reason).startswith(("kw_text:", "kw_path:")) and ":" in str(reason)}
    return min(len(prefixes) * 2.0 + len(keyword_hits) * 1.2, 18.0)


def _keyword_hit_values(reasons: List[str]) -> List[str]:
    values: List[str] = []
    seen = set()
    for reason in reasons:
        text = str(reason)
        if not text.startswith(("kw_text:", "kw_path:")) or ":" not in text:
            continue
        value = text.split(":", 1)[1]
        if value in seen:
            continue
        seen.add(value)
        values.append(value)
    return values


def _has_strong_keyword_hit(keyword_hits: List[str]) -> bool:
    for keyword in keyword_hits:
        stripped = str(keyword).strip()
        if len(stripped) >= 4:
            return True
        if stripped.isascii() and len(stripped) >= 3:
            return True
    return False


def _is_explicit_metadata_match(item: Dict[str, Any]) -> bool:
    return any(str(reason).startswith(("file:", "path:", "dir:")) for reason in item.get("match_reasons") or [])


def _aggregate_file_content_evidence(scored: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in scored:
        source = str(item.get("source") or "")
        if not source.startswith("docs/"):
            continue
        grouped.setdefault(source, []).append(item)

    summaries: List[Dict[str, Any]] = []
    for source, items in grouped.items():
        items.sort(key=lambda item: -float(item.get("score") or 0))
        content_items = [item for item in items if item.get("kind") != "metadata"]
        if not content_items and not any(_is_explicit_metadata_match(item) for item in items):
            continue
        evidence_items = content_items or items
        reasons = _unique_reasons(evidence_items)
        has_explicit_match = any(str(reason).startswith(("file:", "path:", "dir:")) for reason in reasons)
        keyword_hits = _keyword_hit_values(reasons)
        if not has_explicit_match and len(keyword_hits) < 2 and not _has_strong_keyword_hit(keyword_hits):
            continue
        top_score = float(evidence_items[0].get("score") or 0)
        support_score = sum(float(item.get("score") or 0) for item in evidence_items[1:4]) * 0.35
        block_bonus = min(len(content_items), 4) * 1.5
        score = round(top_score + support_score + block_bonus + _reason_diversity_score(reasons), 3)
        previews = []
        for item in evidence_items[:3]:
            location = str(item.get("location") or "file")
            text = preview_text(item.get("text"), 300)
            if text:
                previews.append(f"[{location}] {text}")
        summaries.append(
            {
                "source": source,
                "file_type": evidence_items[0].get("file_type", ""),
                "kind": "file_summary",
                "location": "file",
                "text": "\n".join(previews),
                "metadata": {
                    "block_count": len(items),
                    "content_block_count": len(content_items),
                    "top_locations": [item.get("location") for item in evidence_items[:5]],
                },
                "score": score,
                "match_reasons": reasons,
                "preview": preview_text("\n".join(previews), 260),
            }
        )

    summaries.sort(key=lambda item: (-float(item.get("score") or 0), str(item.get("source") or "")))
    return summaries[:limit]


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
    if query.get("intent") == "file_content_paths":
        return _aggregate_file_content_evidence(scored, limit)
    return scored[:limit]
