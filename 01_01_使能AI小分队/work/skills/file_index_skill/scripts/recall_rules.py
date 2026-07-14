# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any, Dict, List

from file_index_common import (
    COUNTABLE_EXTS,
    apply_metadata_filters,
    filter_categories,
    filter_extensions,
    filter_limit,
    lower_path,
    lower_text,
    normalize_text,
    unique_preserve_order,
)


FILE_PATTERN = re.compile(
    r"[A-Za-z0-9_\-\u4e00-\u9fff\uff00-\uffef（）()、，, .~$]+?\."
    r"(?:docx?|pptx?|xlsx?|xml|java|py|html|md|js|txt|csv|json|ya?ml|properties|env|conf|cfg|ini|log|sh|cmd|sql|pdf)",
    re.IGNORECASE,
)


def extract_extensions(question_title: str) -> List[str]:
    text = lower_text(question_title)
    result: List[str] = []
    for ext in sorted(COUNTABLE_EXTS, key=len, reverse=True):
        patterns = [
            rf"\b{re.escape(ext)}\b",
            rf"{re.escape(ext)}文件",
            rf"{re.escape(ext)} 文件",
            rf"\.{re.escape(ext)}\b",
        ]
        if any(re.search(pattern, text) for pattern in patterns):
            result.append(ext)
    alias_groups = [
        (("word", "word文档", "文字文档"), ["doc", "docx"]),
        (("powerpoint", "演示文稿", "幻灯片"), ["ppt", "pptx"]),
        (("excel", "电子表格", "工作簿"), ["xls", "xlsx"]),
    ]
    for aliases, mapped in alias_groups:
        if any(alias in text for alias in aliases):
            result.extend(mapped)
    return unique_preserve_order(result)


def extract_file_mentions(question_title: str) -> List[str]:
    mentions = []
    for match in FILE_PATTERN.finditer(question_title or ""):
        value = match.group(0).strip(" ，,。；;：:")
        if value:
            mentions.append(value)
    return unique_preserve_order(mentions)


def question_keywords(question_title: str) -> List[str]:
    text = normalize_text(question_title)
    tokens = re.split(r"[\s,，。；;：:、/\\（）()\[\]【】\"'`]+", text)
    stopwords = {
        "",
        "的",
        "文件",
        "数量",
        "统计",
        "全项目",
        "路径",
        "找出",
        "返回",
        "在哪里",
        "修复",
        "责任人为",
        "todo",
        "TODO",
        "事项",
    }
    result = []
    for token in tokens:
        token = token.strip()
        if token in stopwords:
            continue
        if len(token) <= 1 and not token.isascii():
            continue
        result.append(token)
    return unique_preserve_order(result)


def _score_file(item: Dict[str, Any], question_title: str, explicit_files: List[str], extensions: List[str], keywords: List[str]) -> Dict[str, Any] | None:
    score = 0
    reasons: List[str] = []
    path = str(item.get("path") or "")
    name = str(item.get("name") or "")
    stem = str(item.get("stem") or "")
    category = str(item.get("category_dir") or "")
    ext = str(item.get("extension") or "")
    hay_path = lower_path(path)
    hay_name = lower_text(name)
    hay_stem = lower_text(stem)
    hay_category = lower_text(category)
    question = lower_text(question_title)

    for mention in explicit_files:
        mention_lower = lower_text(mention)
        mention_stem = mention_lower.rsplit(".", 1)[0]
        if mention_lower == hay_name:
            score += 100
            reasons.append("exact_filename_match")
        elif mention_lower in hay_path:
            score += 90
            reasons.append("path_filename_match")
        elif mention_stem and mention_stem == hay_stem:
            score += 85
            reasons.append("stem_match")
        elif mention_stem and mention_stem in hay_path:
            score += 70
            reasons.append("partial_filename_match")

    if hay_stem and hay_stem in question:
        score += 90
        reasons.append("stem_in_question")
    if hay_name and hay_name in question:
        score += 100
        reasons.append("name_in_question")
    if hay_category and hay_category in question:
        score += 60
        reasons.append("category_match")
    if ext in extensions:
        score += 40
        reasons.append("extension_match")

    for keyword in keywords:
        keyword_lower = lower_text(keyword)
        if not keyword_lower:
            continue
        if keyword_lower in hay_name:
            score += 25
            reasons.append(f"keyword_name:{keyword}")
        elif keyword_lower in hay_path:
            score += 15
            reasons.append(f"keyword_path:{keyword}")

    if score <= 0:
        return None
    return {
        "path": path,
        "extension": ext,
        "file_type": item.get("file_type") or "other",
        "score": min(score, 300),
        "reason": ",".join(unique_preserve_order(reasons)),
    }


def find_paths(files: List[Dict[str, Any]], question_title: str, payload: Dict[str, Any]) -> List[str]:
    filtered = apply_metadata_filters(files, payload)
    mentions = extract_file_mentions(question_title)
    if not mentions:
        keywords = question_keywords(question_title)
        mentions = [keyword for keyword in keywords if "." in keyword]
    scored = recall_candidates(files, question_title, payload, force_files=filtered)
    if mentions:
        mention_lowers = [lower_text(item) for item in mentions]
        exact = []
        for item in filtered:
            name = lower_text(item.get("name"))
            path = lower_path(item.get("path"))
            stem = lower_text(item.get("stem"))
            for mention in mention_lowers:
                mention_stem = mention.rsplit(".", 1)[0]
                if mention == name or mention in path or mention_stem == stem:
                    exact.append(str(item.get("path")))
        if exact:
            return unique_preserve_order(exact)
    return [item["path"] for item in scored]


def recall_candidates(
    files: List[Dict[str, Any]],
    question_title: str,
    payload: Dict[str, Any],
    force_files: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    filtered = force_files if force_files is not None else apply_metadata_filters(files, payload)
    explicit_files = extract_file_mentions(question_title)
    extensions = extract_extensions(question_title)
    keywords = question_keywords(question_title)
    scored: List[Dict[str, Any]] = []
    for item in filtered:
        result = _score_file(item, question_title, explicit_files, extensions, keywords)
        if result:
            scored.append(result)
    if not scored and (filter_extensions(payload) or filter_categories(payload) or extensions):
        for item in filtered[: filter_limit(payload)]:
            scored.append(
                {
                    "path": str(item.get("path") or ""),
                    "extension": str(item.get("extension") or ""),
                    "file_type": item.get("file_type") or "other",
                    "score": 1,
                    "reason": "filter_fallback",
                }
            )
    scored.sort(key=lambda item: (-int(item.get("score") or 0), str(item.get("path") or "").casefold()))
    return scored[: filter_limit(payload)]
