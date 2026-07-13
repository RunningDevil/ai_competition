# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any, Dict, List

from orchestrator_common import COUNTABLE_EXTS, OFFICE_EXTS, TEXT_CODE_EXTS, normalize_text, unique_preserve_order


FILE_RE = re.compile(
    r"[\w\-\u4e00-\u9fff（）()【】\[\].]+\.("
    r"doc|docx|ppt|pptx|xls|xlsx|xml|java|py|html|md|js|txt|csv|json|yaml|yml|properties|env|conf|cfg|ini|log|sh|cmd"
    r")",
    re.IGNORECASE,
)


def _extract_extensions(title: str) -> List[str]:
    lower = title.lower()
    result: List[str] = []
    for ext in sorted(COUNTABLE_EXTS, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9])\.?{re.escape(ext)}(文件|文档|数量|总数|$|[\s，,。；;])", lower):
            result.append(ext)
    return unique_preserve_order(result)


def _extract_file_names(title: str) -> List[str]:
    return unique_preserve_order(match.group(0).replace("\\", "/") for match in FILE_RE.finditer(title))


def _extract_assignee(title: str) -> str:
    patterns = [
        r"责任人为\s*([^\s，,。；;的]+)",
        r"待\s*([^\s，,。；;]+?)\s*处理",
        r"to\s*[:：]\s*([^\s，,。；;]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, title, flags=re.IGNORECASE)
        if match:
            return normalize_text(match.group(1))
    return ""


def _extract_end_date(title: str) -> str:
    match = re.search(r"(20\d{6})", title)
    return match.group(1) if match else ""


def _base_filters(title: str) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    assignee = _extract_assignee(title)
    if assignee:
        filters["assignee"] = assignee
        filters["to"] = assignee
    end_date = _extract_end_date(title)
    if end_date:
        filters["end_date"] = end_date
    files = _extract_file_names(title)
    if files:
        filters["file_name"] = files[0]
    exts = _extract_extensions(title)
    if exts:
        filters["extensions"] = exts
        if len(exts) == 1:
            filters["extension"] = exts[0]
    return filters


def classify_question(question: Dict[str, Any]) -> Dict[str, Any]:
    title = normalize_text(question.get("title"))
    lower = title.lower()
    files = _extract_file_names(title)
    extensions = _extract_extensions(title)
    filters = _base_filters(title)

    classification: Dict[str, Any] = {
        "category": "knowledge_qa",
        "task_type": "answer_from_context",
        "filters": filters,
        "files": files,
        "extensions": extensions,
        "candidate_strategy": "recall",
        "target_agent": "knowledge_qa",
        "notes": [],
    }

    if extensions and any(word in title for word in ("数量", "总数量", "总数", "多少", "几个")):
        classification.update(
            {
                "category": "file_count",
                "task_type": "count_by_type",
                "target_agent": "file_index",
                "candidate_strategy": "none",
            }
        )
        return classification

    if files and any(word in title for word in ("路径", "位置", "找出", "在哪", "查找")):
        classification.update(
            {
                "category": "find_path",
                "task_type": "find_path",
                "target_agent": "file_index",
                "candidate_strategy": "none",
            }
        )
        return classification

    is_fix = any(word in title for word in ("修复", "修改", "改成", "优化整理")) or re.search(r"完成.*描述的工作", title)
    has_todo = "todo" in lower or "TODO" in title
    has_comment = any(word in title for word in ("批注", "注释", "待办"))
    is_count = any(word in title for word in ("统计", "数量", "多少", "几个"))
    is_list_request = any(word in title for word in ("列表", "清单", "明细", "列出"))
    is_filter = bool(filters.get("assignee") or filters.get("end_date")) or any(word in title for word in ("责任人", "待", "日期"))

    if is_fix and (has_todo or has_comment or files):
        family = _annotation_family(title, files, extensions, has_todo)
        classification.update(
            {
                "category": "fix_annotation",
                "task_type": _annotation_task_type("fix", family),
                "target_agent": family,
                "candidate_strategy": "targeted_or_all",
            }
        )
        return classification

    if (has_todo or has_comment) and (is_filter or is_list_request):
        family = _annotation_family(title, files, extensions, has_todo)
        classification.update(
            {
                "category": "filter_annotation",
                "task_type": _annotation_task_type("filter", family),
                "target_agent": family,
                "candidate_strategy": "targeted_or_all",
            }
        )
        return classification

    if (has_todo or has_comment) and is_count:
        family = _annotation_family(title, files, extensions, has_todo)
        classification.update(
            {
                "category": "count_annotation",
                "task_type": _annotation_task_type("count", family),
                "target_agent": family,
                "candidate_strategy": "targeted_or_all",
            }
        )
        return classification

    if (has_todo or has_comment) and is_filter:
        family = _annotation_family(title, files, extensions, has_todo)
        classification.update(
            {
                "category": "filter_annotation",
                "task_type": _annotation_task_type("filter", family),
                "target_agent": family,
                "candidate_strategy": "targeted_or_all",
            }
        )
        return classification

    if any(word in title for word in ("环境", "密码", "账号", "用户", "端口", "地址")) or re.search(r"\d{1,3}(?:\.\d{1,3}){3}", title):
        filters.setdefault("categories", ["02_环境信息"])
        filters.setdefault("extensions", ["md"])
        filters.setdefault("limit", 10)
        classification.update({"task_type": "answer_environment_info", "candidate_strategy": "recall", "filters": filters})
    elif any(word in title for word in ("命令", "控制台", "连接", "如何", "怎么")):
        classification.update({"task_type": "answer_command_info", "candidate_strategy": "recall"})
    elif any(word in title for word in ("excel", "Excel", "表格", "透视", "sheet", "工作表")) or any(ext in {"xls", "xlsx"} for ext in extensions):
        classification.update({"task_type": "answer_excel_summary", "candidate_strategy": "recall"})
    elif any(word in title for word in ("代码", "脚本", "执行结果", "风险", "静态")) or any(ext in {"py", "java", "js"} for ext in extensions):
        classification.update({"task_type": "answer_code_static_question", "candidate_strategy": "recall"})
    elif any(word in title for word in ("涉及", "相关", "文件名称", "路径")):
        classification.update({"task_type": "answer_file_content_paths", "candidate_strategy": "recall"})
    return classification


def _annotation_family(title: str, files: List[str], extensions: List[str], has_todo: bool) -> str:
    file_exts = {file_name.rsplit(".", 1)[-1].lower() for file_name in files if "." in file_name}
    ext_set = set(extensions) | file_exts
    if ext_set & OFFICE_EXTS:
        return "office"
    if ext_set & TEXT_CODE_EXTS:
        return "text_code"
    if has_todo:
        return "all"
    if any(word in title for word in ("word", "Word", "ppt", "PPT", "excel", "Excel", "办公")):
        return "office"
    return "all"


def _annotation_task_type(action: str, family: str) -> str:
    if family == "text_code":
        return {"filter": "filter_todos", "count": "count_todos", "fix": "fix_todos"}[action]
    if family == "office":
        return {"filter": "filter_comments", "count": "count_comments", "fix": "fix_comments"}[action]
    return {"filter": "filter_annotations", "count": "count_annotations", "fix": "fix_annotations"}[action]
