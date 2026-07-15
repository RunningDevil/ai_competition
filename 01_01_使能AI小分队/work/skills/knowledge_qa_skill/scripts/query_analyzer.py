# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any, Dict, List

from qa_common import COUNTABLE_EXTS, normalize_path_text, normalize_text, unique_preserve_order


FILE_RE = re.compile(
    r"[\w\-\u4e00-\u9fff（）()【】\[\].]+\.("
    r"docx|doc|pptx|ppt|xlsx|xls|xml|java|py|html|md|js|txt|csv|json|yaml|yml|properties|env|conf|cfg|ini|log|sh|cmd|sql|pdf"
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
    "指令",
    "命令行",
    "控制台",
    "终端",
    "客户端",
    "连接",
    "登录",
    "访问",
    "数据库",
    "高斯",
    "配置",
    "产品",
    "报价",
    "流程",
    "开发",
    "部署",
    "上线",
    "发布",
    "运行",
    "接口",
    "风险",
    "删除",
    "脚本",
    "透视",
    "表格",
    "统计",
]

SEMANTIC_KEYWORD_GROUPS = [
    ("上线", "发布", "部署", "投产", "上线流程", "发布流程", "部署流程"),
    ("数据库", "db", "DB", "高斯", "高斯数据库", "GaussDB", "gsql", "psql", "mysql", "jdbc"),
    ("账号", "用户", "用户名", "user", "login", "登录"),
    ("密码", "口令", "凭据", "credential", "secret", "password", "pwd"),
    ("开源", "开放源代码", "OSS", "open source"),
    ("需求", "规格", "设计", "方案", "需求设计"),
    ("命令", "指令", "命令行", "语句", "shell", "脚本", "控制台", "终端", "客户端", "连接", "登录", "访问"),
    ("ssh", "scp", "sftp", "远程登录", "远程连接", "服务器登录", "登录服务器"),
    ("curl", "wget", "http", "https", "接口调用", "下载"),
    ("kubectl", "k8s", "kubernetes", "pod", "集群"),
    ("docker", "docker-compose", "容器", "镜像"),
    ("systemctl", "journalctl", "服务", "日志"),
    ("风险", "漏洞", "安全", "高危", "危险"),
    ("审批", "评审", "审核", "review"),
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
            if len(token) <= 24:
                for size in (2, 3):
                    for i in range(0, len(token) - size + 1):
                        gram = token[i : i + size]
                        if gram not in STOPWORDS:
                            tokens.append(gram)
    return unique_preserve_order(tokens)


def _expand_semantic_keywords(keywords: List[str]) -> List[str]:
    expanded: List[str] = []
    for keyword in keywords:
        expanded.append(keyword)
        keyword_lower = keyword.lower()
        for group in SEMANTIC_KEYWORD_GROUPS:
            group_lowers = [item.lower() for item in group]
            if any(
                item_lower
                and (
                    item_lower == keyword_lower
                    or (len(item_lower) >= 3 and item_lower in keyword_lower)
                    or (len(keyword_lower) >= 3 and keyword_lower in item_lower)
                )
                for item_lower in group_lowers
            ):
                expanded.extend(group)
    return unique_preserve_order(expanded)


def _extract_required_phrases(title: str) -> List[str]:
    phrases: List[str] = []
    cleaned = title
    patterns = [
        r"(?:涉及|关于|围绕|属于|面向)\s*([A-Za-z0-9_\-\s\u4e00-\u9fff]{2,30}?)(?:业务|项目|主题|模块|系统|功能|场景)",
        r"([A-Za-z0-9_\-\s\u4e00-\u9fff]{2,30}?)(?:业务|项目|主题|模块|系统|功能|场景)\s*(?:相关|有关|涉及)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, cleaned, flags=re.IGNORECASE):
            phrase = _clean_required_phrase(match.group(1))
            if phrase:
                phrases.append(phrase)
    return unique_preserve_order(phrases)


def _clean_required_phrase(value: str) -> str:
    text = normalize_text(value)
    text = re.sub(r"(?:目录|文件夹)?[下中里内]$", "", text)
    text = re.sub(r"^(?:筛选出|检索|找出|查找|输出|返回|列出|所有|全部|相关|涉及|关于|围绕|属于|面向)+", "", text)
    text = re.sub(r"(?:相关|有关|涉及|文件|文档|资料|路径|名称|列表|清单)+$", "", text)
    text = text.strip(" 的-_/，,。；;：:？?（）()[]【】\"'")
    if len(text) < 2:
        return ""
    if text in STOPWORDS:
        return ""
    return text


def _required_phrase_terms(phrase: str) -> List[str]:
    text = normalize_text(phrase)
    if re.fullmatch(r"[A-Za-z0-9_\-\s]+", text):
        return [part for part in re.split(r"[\s_-]+", text) if len(part) >= 2]
    terms: List[str] = []
    if re.fullmatch(r"[\u4e00-\u9fff]+", text):
        if len(text) <= 3:
            terms.append(text)
        elif len(text) == 4:
            terms.extend([text[:2], text[2:]])
        elif len(text) in {5, 6}:
            terms.extend([text[:3], text[3:]])
        else:
            terms.extend(text[index : index + 2] for index in range(0, len(text), 2))
    else:
        for token in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_-]{2,}", text):
            if token not in STOPWORDS:
                terms.append(token)
    return unique_preserve_order(terms)


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


def _expects_code_execution_result(title: str) -> bool:
    lower = title.lower()
    if any(word in title for word in ("执行结果", "运行结果", "输出结果", "返回结果", "返回值", "执行后", "运行后", "打印结果")):
        return True
    if any(word in lower for word in ("return value", "output", "print result", "execution result", "run result")):
        return True
    return bool(re.search(r"(结果|返回|输出).*(是多少|是什么|为多少|为何)", title))


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
    keywords = _expand_semantic_keywords(unique_preserve_order(extra_keywords + explicit_files + docs_paths + _extract_keywords(title)))
    required_phrases = _extract_required_phrases(title)
    return {
        "title": title,
        "task_type": task_type,
        "intent": intent,
        "expects_code_execution_result": _expects_code_execution_result(title),
        "keywords": keywords,
        "required_phrases": required_phrases,
        "required_phrase_terms": [_required_phrase_terms(phrase) for phrase in required_phrases],
        "files": unique_preserve_order(explicit_files),
        "docs_paths": unique_preserve_order(docs_paths),
        "extensions": unique_preserve_order(extensions),
        "directories": unique_preserve_order(directories),
        "expects_count": any(word in title for word in ("数量", "多少", "几个", "总数")),
        "ips": IP_RE.findall(title),
    }
