# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any, Dict, List

from qa_common import COUNTABLE_EXTS, normalize_path_text, normalize_text, unique_preserve_order


FILE_RE = re.compile(
    r"[\w\-\u4e00-\u9fff（）()【】\[\].]+\.("
    r"doc|docx|ppt|pptx|xls|xlsx|xml|java|py|html|md|js|txt|csv|json|yaml|yml|properties|env|conf|cfg|ini|log|sh|cmd"
    r")",
    re.IGNORECASE,
)
DOCS_PATH_RE = re.compile(r"docs/[^\s，,。；;]+", re.IGNORECASE)
IP_RE = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b")

CHINESE_HINTS = [
    "业务",
    "需求",
    "设计",
    "技术",
    "环境",
    "密码",
    "账号",
    "用户",
    "端口",
    "地址",
    "命令",
    "控制台",
    "连接",
    "数据库",
    "高斯",
    "配置",
    "产品",
    "报价",
    "流程",
    "开发",
    "部署",
    "运行",
    "接口",
    "风险",
    "删除",
    "脚本",
    "透视",
    "表格",
    "统计",
]

STOPWORDS = {
    "的",
    "了",
    "和",
    "与",
    "或",
    "在",
    "中",
    "里",
    "请",
    "帮我",
    "如何",
    "怎么",
    "什么",
    "哪些",
    "是否",
    "完成",
    "描述",
    "工作",
    "文件",
    "路径",
    "名称",
    "数量",
    "统计",
    "返回",
    "输出",
    "获取",
    "查询",
    "找出",
}


def _extract_extensions(title: str) -> List[str]:
    lower = title.lower()
    found: List[str] = []
    for ext in sorted(COUNTABLE_EXTS, key=len, reverse=True):
        if re.search(rf"(?<![a-z0-9])\.?{re.escape(ext)}(文件|文档|数量|总数|$|[\s，,。；;])", lower):
            found.append(ext)
    return unique_preserve_order(found)


def _extract_keywords(title: str) -> List[str]:
    tokens: List[str] = []
    cleaned = re.sub(r"[，,。；;：:？?！!（）()\[\]【】\"'`]", " ", title)
    for token in re.findall(r"[A-Za-z0-9_./-]+|[\u4e00-\u9fff]{2,}", cleaned):
        token = normalize_text(token)
        if not token or token in STOPWORDS:
            continue
        if token.lower() in COUNTABLE_EXTS:
            continue
        tokens.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]{4,}", token):
            for hint in CHINESE_HINTS:
                if hint in token:
                    tokens.append(hint)
            if len(token) <= 10:
                for size in (2, 3):
                    for i in range(0, len(token) - size + 1):
                        gram = token[i : i + size]
                        if gram not in STOPWORDS:
                            tokens.append(gram)
    return unique_preserve_order(tokens)


def _detect_intent(title: str, task_type: str) -> str:
    if task_type in {
        "answer_file_content_paths",
        "answer_environment_info",
        "answer_command_info",
        "answer_excel_summary",
        "answer_code_static_question",
    }:
        return task_type.replace("answer_", "")
    lower = title.lower()
    if "excel" in lower or "xlsx" in lower or "xls" in lower or any(word in title for word in ("表格", "透视", "sheet", "工作表")):
        return "excel_summary"
    if any(word in title for word in ("环境", "密码", "账号", "用户", "端口", "地址")) or IP_RE.search(title):
        return "environment_info"
    if any(word in title for word in ("命令", "控制台", "连接", "如何", "怎么")):
        return "command_info"
    if any(word in title for word in ("代码", "脚本", "执行结果", "风险", "静态")) or re.search(r"\.(py|java|js)\b", lower):
        return "code_static_question"
    if any(word in title for word in ("涉及", "相关", "文件名", "文件名称", "路径", "在哪")):
        return "file_content_paths"
    return "from_context"


def analyze_query(payload: Dict[str, Any]) -> Dict[str, Any]:
    title = normalize_text(payload.get("question_title") or payload.get("title"))
    task_type = normalize_text(payload.get("task_type"))
    file_names = FILE_RE.findall(title)
    explicit_files = [normalize_path_text(match.group(0)) for match in FILE_RE.finditer(title)]
    docs_paths = [normalize_path_text(match.group(0)) for match in DOCS_PATH_RE.finditer(title)]
    filters = payload.get("filters") or {}

    if filters.get("file_name"):
        explicit_files.append(normalize_path_text(filters.get("file_name")))
    if filters.get("keyword"):
        extra_keywords = [normalize_text(filters.get("keyword"))]
    else:
        extra_keywords = []

    extensions = _extract_extensions(title)
    if filters.get("extension"):
        extensions.append(str(filters.get("extension")).lower().lstrip("."))
    if filters.get("extensions"):
        extensions.extend(str(item).lower().lstrip(".") for item in filters.get("extensions") or [])

    directories = []
    for path in docs_paths:
        parts = path.split("/")
        if len(parts) >= 2:
            directories.append("/".join(parts[:2]))

    intent = _detect_intent(title, task_type)
    keywords = unique_preserve_order(extra_keywords + explicit_files + docs_paths + _extract_keywords(title))
    return {
        "title": title,
        "task_type": task_type,
        "intent": intent,
        "keywords": keywords,
        "files": unique_preserve_order(explicit_files),
        "docs_paths": unique_preserve_order(docs_paths),
        "extensions": unique_preserve_order(extensions),
        "directories": unique_preserve_order(directories),
        "expects_count": any(word in title for word in ("数量", "多少", "几个", "总数")),
        "ips": IP_RE.findall(title),
    }
