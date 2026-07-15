# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any, Dict, List

from orchestrator_common import COUNTABLE_EXTS, OFFICE_EXTS, TEXT_CODE_EXTS, normalize_text, unique_preserve_order


FILE_RE = re.compile(
    r"[\w\-\u4e00-\u9fff（）()【】\[\].]+\.("
    r"docx|doc|pptx|ppt|xlsx|xls|xml|java|py|html|md|js|txt|csv|json|yaml|yml|properties|env|conf|cfg|ini|log|sh|cmd|sql|pdf"
    r")",
    re.IGNORECASE,
)
PATH_SCOPE_RE = re.compile(r"(docs/[^\s，,。；;]+?)(?:目录|文件夹|下|中|里|内)", re.IGNORECASE)

COUNT_WORDS = (
    "数量",
    "总数量",
    "总数",
    "多少",
    "几个",
    "几份",
    "多少个",
    "多少份",
    "共有",
    "一共",
    "总共",
    "合计",
    "总计",
    "分别有多少",
    "各有多少",
)

EXTENSION_ALIASES = [
    (("word", "Word", "WORD", "Word文档", "word文档", "文字文档"), ["doc", "docx"]),
    (("powerpoint", "PowerPoint", "演示文稿", "幻灯片"), ["ppt", "pptx"]),
    (("excel", "Excel", "EXCEL", "电子表格", "工作簿"), ["xls", "xlsx"]),
    (("markdown", "Markdown", "md文件", "MD文件"), ["md"]),
    (("javascript", "JavaScript", "js文件", "JS文件"), ["js"]),
    (("java文件", "Java文件"), ["java"]),
    (("python", "Python", "py文件", "PY文件"), ["py"]),
]


def _extract_extensions(title: str) -> List[str]:
    lower = title.lower()
    result: List[str] = []
    for ext in sorted(COUNTABLE_EXTS, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9])\.?{re.escape(ext)}(?![a-z0-9])", lower):
            result.append(ext)
    if result:
        return unique_preserve_order(result)
    for aliases, mapped_exts in EXTENSION_ALIASES:
        if any(alias.lower() in lower for alias in aliases):
            result.extend(mapped_exts)
    if "代码文件" in title or "代码类文件" in title:
        result.extend(sorted(TEXT_CODE_EXTS))
    return unique_preserve_order(result)


def _extract_file_names(title: str) -> List[str]:
    return unique_preserve_order(match.group(0).replace("\\", "/") for match in FILE_RE.finditer(title))


def _extract_path_scopes(title: str) -> List[str]:
    scopes: List[str] = []
    for match in PATH_SCOPE_RE.finditer(title):
        scope = match.group(1).replace("\\", "/").strip(" /，,。；;")
        if scope and "." not in scope.rsplit("/", 1)[-1]:
            scopes.append(scope)
    return unique_preserve_order(scopes)


def _extract_assignee(title: str) -> str:
    patterns = [
        r"责任人为\s*([^\s，,。；;的且并和及、]+)",
        r"待\s*([^\s，,。；;]+?)\s*处理",
        r"to\s*[:：]\s*([^\s，,。；;]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, title, flags=re.IGNORECASE)
        if match:
            return normalize_text(match.group(1))
    return ""


def _extract_date_filters(title: str) -> Dict[str, Any]:
    date_matches = list(re.finditer(r"(20\d{6})", title))
    dates = [match.group(1) for match in date_matches]
    if not dates:
        return {}
    if len(dates) >= 2:
        start, end = dates[0], dates[1]
        if start > end:
            start, end = end, start
        return {"end_date_gte": start, "end_date_lte": end, "end_date_range": [start, end]}

    date = dates[0]
    match = date_matches[0]
    before_text = title[max(0, match.start() - 10) : match.start()]
    after_text = title[match.end() : match.end() + 10]
    if "早于" in before_text:
        return {"end_date_lt": date}
    if "晚于" in before_text:
        return {"end_date_gt": date}
    if any(word in after_text for word in ("之前", "以前", "及之前", "及以前", "当天及之前", "前")) or any(
        word in before_text for word in ("不晚于", "截至", "截止", "截止到")
    ):
        return {"end_date_lte": date}
    if any(word in after_text for word in ("之后", "以后", "及之后", "及以后", "当天及之后", "起", "以来")) or any(
        word in before_text for word in ("不早于", "从", "自")
    ):
        return {"end_date_gte": date}
    return {"end_date": date}


def _base_filters(title: str) -> Dict[str, Any]:
    filters: Dict[str, Any] = {}
    assignee = _extract_assignee(title)
    if assignee:
        filters["assignee"] = assignee
        filters["to"] = assignee
    filters.update(_extract_date_filters(title))
    files = _extract_file_names(title)
    if files:
        filters["file_name"] = files[0]
    path_scopes = _extract_path_scopes(title)
    if path_scopes:
        filters["path_scopes"] = path_scopes
        filters["path_scope"] = path_scopes[0]
    exts = _extract_extensions(title)
    if exts:
        filters["extensions"] = exts
        if len(exts) == 1:
            filters["extension"] = exts[0]
    return filters


def _is_file_count_question(title: str, extensions: List[str]) -> bool:
    if any(word in title for word in ("批注", "注释", "待办", "TODO", "todo")):
        return False
    if extensions and any(word in title for word in COUNT_WORDS):
        return True
    if any(word in title for word in ("文件数量", "文档数量", "资料数量", "文件总数", "文档总数")):
        return True
    if re.search(r"(项目|知识库|docs|目录|文件夹).{0,12}(共有|一共|总共|合计|总计|有).{0,12}(多少|几).{0,4}(文件|文档|资料|个|份)", title, flags=re.IGNORECASE):
        return True
    if re.search(r"(文件|文档|资料).{0,6}(共有|一共|总共|合计|总计|有).{0,8}(多少|几).{0,4}(个|份)?", title):
        return True
    if re.search(r"(多少|几).{0,4}(个|份)?(文件|文档|资料)", title):
        return True
    return False


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

    is_fix = any(word in title for word in ("修复", "修改", "改成", "优化整理")) or re.search(r"完成.*描述的工作", title)
    has_todo = "todo" in lower or "TODO" in title
    has_comment = any(word in title for word in ("批注", "注释", "待办"))
    is_count = any(word in title for word in ("统计", "数量", "多少", "几个"))
    is_list_request = any(word in title for word in ("列表", "清单", "明细", "列出"))
    has_date_filter = any(filters.get(key) for key in ("end_date", "end_date_lte", "end_date_gte", "end_date_lt", "end_date_gt", "end_date_range"))
    is_filter = bool(filters.get("assignee") or has_date_filter) or any(word in title for word in ("责任人", "待", "日期", "之前", "以后", "早于", "晚于", "区间", "范围"))

    if _is_file_count_question(title, extensions):
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

    if (has_todo or has_comment) and is_count and any(word in title for word in ("各责任人", "每个责任人", "不同责任人")):
        family = _annotation_family(title, files, extensions, has_todo)
        classification.update(
            {
                "category": "aggregate_annotation",
                "task_type": "aggregate_annotations",
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
    has_office_ext = bool(ext_set & OFFICE_EXTS)
    has_text_code_ext = bool(ext_set & TEXT_CODE_EXTS)
    mentions_office = any(word in title for word in ("word", "Word", "ppt", "PPT", "excel", "Excel", "办公", "Word", "PPT", "Excel"))
    mentions_code = any(word in title for word in ("代码", "java", "Java", "js", "JS", "javascript", "JavaScript", "py", "Python", "html", "HTML", "xml", "XML", "md", "Markdown"))
    if (has_office_ext and has_text_code_ext) or (mentions_office and mentions_code):
        return "all"
    if has_office_ext:
        return "office"
    if has_text_code_ext:
        return "text_code"
    if mentions_code and not mentions_office:
        return "text_code"
    if has_todo:
        return "all"
    if mentions_office:
        return "office"
    return "all"


def _annotation_task_type(action: str, family: str) -> str:
    if family == "text_code":
        return {"filter": "filter_todos", "count": "count_todos", "fix": "fix_todos"}[action]
    if family == "office":
        return {"filter": "filter_comments", "count": "count_comments", "fix": "fix_comments"}[action]
    return {"filter": "filter_annotations", "count": "count_annotations", "fix": "fix_annotations"}[action]
