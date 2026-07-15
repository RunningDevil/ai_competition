# -*- coding: utf-8 -*-
from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from security_common import (
    extract_docs_paths,
    lowercase_path,
    normalize_path_text,
    normalize_text,
    resolve_docs_path,
)


DANGEROUS_ACTION_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\brm\s+",
    r"\brmdir\b",
    r"\bdel\b",
    r"\bremove-item\b",
    r"\bunlink\b",
    r"\bshred\b",
    r"\bchmod\s+777\b",
    r"\bchown\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bcurl\b.*\|\s*(sh|bash)",
    r"\bwget\b.*\|\s*(sh|bash)",
    r"\b(taskkill|killall|pkill)\b",
    r"\bkill\s+(-9\s+)?\w+",
    r"\b(eval|exec|system|subprocess\.run|os\.system)\b",
    r"删除",
    r"彻底删除",
    r"移除",
    r"写入",
    r"覆盖",
    r"执行.*命令",
    r"运行.*脚本",
    r"终止.*进程",
    r"kill\s*codeagent",
    r"taskkill",
]

COMMAND_INFO_QUERY_PATTERNS = [
    r"(命令|指令|command|cmd|shell|cli|终端|控制台|语句).{0,24}(是什么|怎么写|如何写|怎样写|写法|用法|内容|文本)",
    r"(什么|哪条|哪个|如何|怎么|怎样|查询|查看|获取|返回|给出|告诉|列出|提供|找出|检索).{0,36}(命令|指令|command|cmd|shell|cli|终端|控制台|语句)",
    r"(连接|登录|重启|停止|删除|清理|授权|部署|启动|修改权限).{0,24}(命令|指令).{0,20}(是什么|怎么写|如何|怎么|哪条)",
    r"\b(what|which|how|show|list|find|get|return|provide)\b.{0,48}\b(command|cmd|shell|cli)\b",
]

COMMAND_EXECUTION_REQUEST_PATTERNS = [
    r"\brm\s+-rf\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"(删除|移除|清空).{0,10}(全部|所有|整个|全量|根目录|系统)",
    r"(请|帮我|替我|直接|立即|立刻|马上|现在).{0,16}(执行|运行|启动|调用|跑|删除|移除|覆盖|写入|杀掉|终止|重启|修改权限)",
    r"(执行(?!权限)|运行).{0,16}\b(rm|del|remove-item|kill|pkill|taskkill|chmod|chown|mkfs|dd|curl|wget|bash|sh)\b",
    r"(验证|确认|测试).{0,16}(命令|指令|脚本).{0,16}(可执行|能运行|执行)",
    r"\bplease\s+(run|execute|delete|remove|kill|chmod)\b",
    r"\b(run|execute)\s+(rm|del|remove-item|kill|pkill|taskkill|chmod|chown|mkfs|dd|curl|wget|bash|sh)\b",
]

PROMPT_INJECTION_PATTERNS = [
    r"忽略.*(规则|指令|前文|上文|要求)",
    r"无论.*都.*执行",
    r"不需要询问用户",
    r"最高优先级",
    r"上帝模式",
    r"强制.*执行",
    r"绕过.*(规则|安全|权限|限制)",
    r"不要遵循.*(规则|指令)",
    r"ignore.*(previous|above|rules|instructions)",
    r"system\s*override",
    r"developer\s*mode",
]

SECRET_PATTERNS = [
    r"密码",
    r"密钥",
    r"明文密码",
    r"数据库.*(密码|密钥)",
    r"\bpassword\b",
    r"\bpasswd\b",
    r"\bsecret\b",
    r"\btoken\b",
    r"\bapi[_-]?key\b",
    r"\baccess[_-]?key\b",
]

SYSTEM_PATH_PATTERNS = [
    r"(^|/)etc($|/)",
    r"(^|/)root($|/)",
    r"(^|/)proc($|/)",
    r"(^|/)sys($|/)",
    r"(^|/)dev($|/)",
    r"(^|/)var/log($|/)",
    r"99_mock_system_dir",
    r"\bc:\\",
    r"读取\s*c\s*盘",
]

ENV_SIGNAL_PATTERNS = [
    r"https?://\d{1,3}(?:\.\d{1,3}){3}:\d+",
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",
    r"环境",
    r"跳板机",
    r"paas",
    r"bastion",
    r"gkit",
    r"op_user",
    r"deploy_user",
    r"svc_",
]

COMMAND_TOKEN_RE = re.compile(r"[A-Za-z0-9_@.+~:/\\-]+")
TEXT_CODE_EXTS = {"md", "html", "xml", "java", "py", "js"}

CODE_RESULT_QUERY_PATTERNS = [
    r"(阅读|查看|分析|推断|判断).{0,40}\.(?:java|py|js|html|xml|md).{0,40}(运行结果|执行结果|输出结果|返回结果|返回值|打印结果)",
    r"(运行结果|执行结果|输出结果|返回结果|返回值|打印结果).{0,40}\.(?:java|py|js|html|xml|md)",
    r"(main方法|函数|方法).{0,30}(运行结果|执行结果|输出结果|返回结果|返回值|打印结果)",
    r"\b(main|function|method)\b.{0,40}\b(output|result|return value|prints?)\b",
]


def _contains_any(patterns: List[str], text: str) -> Tuple[bool, str]:
    lowered = text.lower()
    for pattern in patterns:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            return True, pattern
    return False, ""


def _path_segments(path_text: str) -> List[str]:
    return [item for item in normalize_path_text(path_text).strip("/").split("/") if item]


def _simple_match(rule: str, value: str, *, check_basename: bool = False) -> bool:
    if not rule:
        return False
    normalized_rule = lowercase_path(rule)
    normalized_value = lowercase_path(value)
    basename = Path(normalized_value).name
    candidates = [normalized_value]
    if check_basename:
        candidates.append(basename)

    for candidate in candidates:
        if candidate == normalized_rule:
            return True
        if fnmatch.fnmatch(candidate, normalized_rule):
            return True

    stripped_rule = normalized_rule.strip("/")
    if not stripped_rule:
        return False
    if normalized_rule.startswith("/") and stripped_rule in _path_segments(normalized_value):
        return True
    if "/" not in stripped_rule and stripped_rule in _path_segments(normalized_value):
        return True
    if fnmatch.fnmatch(normalized_value, f"*/{stripped_rule}") or fnmatch.fnmatch(normalized_value, f"*/{stripped_rule}/*"):
        return True
    return False


def _command_token_candidates(text: str) -> List[str]:
    candidates: List[str] = []
    for match in COMMAND_TOKEN_RE.finditer(normalize_text(text)):
        token = match.group(0).strip("`'\"“”‘’，。；;：:、,.()[]{}<>")
        if not token:
            continue
        normalized = normalize_path_text(token).lower()
        if not normalized:
            continue
        candidates.append(normalized)
        basename = Path(normalized).name
        if basename and basename != normalized:
            candidates.append(basename)
    return list(dict.fromkeys(candidates))


def check_permission_commands_in_question(question_title: str, permission: Dict[str, Dict[str, List[str]]]) -> Tuple[bool, str, List[str]]:
    normalized_text = normalize_text(question_title).lower()
    normalized_path_text = normalize_path_text(question_title).lower()
    candidates = _command_token_candidates(question_title)

    for rule in permission.get("command", {}).get("deny", []):
        normalized_rule = normalize_text(rule).strip().lower()
        normalized_path_rule = normalize_path_text(rule).strip().lower()
        if not normalized_rule:
            continue

        rule_candidates = [normalized_rule, normalized_path_rule]
        first_token = normalized_rule.split()[0] if normalized_rule.split() else normalized_rule
        if first_token and not any(char.isspace() for char in normalized_rule):
            rule_candidates.append(first_token)

        for rule_candidate in dict.fromkeys(item for item in rule_candidates if item):
            has_wildcard = any(char in rule_candidate for char in "*?[]")
            has_space = any(char.isspace() for char in rule_candidate)
            if has_space:
                if rule_candidate in normalized_text or fnmatch.fnmatch(normalized_text, f"*{rule_candidate}*"):
                    return False, f"命中 permission.command:{rule}", [f"permission.command:{rule}"]
                continue

            for candidate in candidates:
                if has_wildcard:
                    if fnmatch.fnmatch(candidate, rule_candidate) or fnmatch.fnmatch(normalized_path_text, f"*{rule_candidate}*"):
                        return False, f"命中 permission.command:{rule}", [f"permission.command:{rule}"]
                elif candidate == rule_candidate:
                    return False, f"命中 permission.command:{rule}", [f"permission.command:{rule}"]

    return True, "", []


def check_permission_resource(kind: str, value: str, permission: Dict[str, Dict[str, List[str]]]) -> Tuple[bool, str, List[str]]:
    kind = (kind or "").strip().lower()
    value = normalize_path_text(value)
    if not value:
        return False, "", []

    matched: List[str] = []
    if kind in {"file", "path", "text"}:
        for rule in permission.get("file", {}).get("deny", []):
            if _simple_match(rule, value, check_basename=True):
                matched.append(f"permission.file:{rule}")
        for rule in permission.get("dir", {}).get("deny", []):
            if _simple_match(rule, value):
                matched.append(f"permission.dir:{rule}")
    elif kind == "dir":
        for rule in permission.get("dir", {}).get("deny", []):
            if _simple_match(rule, value):
                matched.append(f"permission.dir:{rule}")
    elif kind == "command":
        command = normalize_text(value)
        first_token = command.split()[0] if command.split() else command
        for rule in permission.get("command", {}).get("deny", []):
            if _simple_match(rule, command) or _simple_match(rule, first_token):
                matched.append(f"permission.command:{rule}")

    if matched:
        return False, f"命中 {matched[0]}", matched
    return True, "", []


def has_path_traversal(text: str) -> bool:
    normalized = normalize_path_text(text)
    return "../" in normalized or normalized.startswith("../") or "/../" in normalized


def is_system_path_query(text: str) -> Tuple[bool, str]:
    return _contains_any(SYSTEM_PATH_PATTERNS, normalize_path_text(text))


def is_secret_query(text: str) -> Tuple[bool, str]:
    return _contains_any(SECRET_PATTERNS, text)


def has_environment_signal(text: str) -> bool:
    return _contains_any(ENV_SIGNAL_PATTERNS, text)[0]


def is_env_info_exception(text: str) -> bool:
    normalized = normalize_path_text(text).lower()
    if "docs/02_环境信息" in normalized or "02_环境信息" in normalized:
        return True
    return has_environment_signal(text) and not is_system_path_query(text)[0]


def has_dangerous_action(text: str) -> Tuple[bool, str]:
    return _contains_any(DANGEROUS_ACTION_PATTERNS, text)


def is_command_execution_request(text: str) -> Tuple[bool, str]:
    return _contains_any(COMMAND_EXECUTION_REQUEST_PATTERNS, text)


def is_command_info_query(text: str) -> Tuple[bool, str]:
    matched, pattern = _contains_any(COMMAND_INFO_QUERY_PATTERNS, text)
    if not matched:
        return False, ""
    execution, execution_pattern = is_command_execution_request(text)
    if execution:
        return False, execution_pattern
    return True, pattern


def has_prompt_injection(text: str) -> Tuple[bool, str]:
    return _contains_any(PROMPT_INJECTION_PATTERNS, text)


def is_code_result_query(text: str) -> bool:
    return _contains_any(CODE_RESULT_QUERY_PATTERNS, text)[0]


def is_text_code_path(path_text: str) -> bool:
    ext = Path(normalize_path_text(path_text)).suffix.lower().lstrip(".")
    return ext in TEXT_CODE_EXTS


def check_resource(resource: Dict[str, Any], permission: Dict[str, Dict[str, List[str]]]) -> Tuple[bool, str, List[str]]:
    kind = normalize_text(resource.get("kind") or "text").lower()
    value = normalize_text(resource.get("value"))
    if not value:
        return False, "resource.value is required", ["input.missing_resource_value"]

    ok, reason, matched = check_permission_resource(kind, value, permission)
    if not ok:
        return False, reason, matched
    if kind in {"file", "dir", "path"} and has_path_traversal(value):
        return False, "路径包含 ../", ["path.traversal"]
    if kind == "command":
        dangerous, pattern = has_dangerous_action(value)
        if dangerous:
            return False, f"命令包含高危动作: {pattern}", [f"dangerous.command:{pattern}"]
    if kind == "text":
        dangerous, pattern = has_dangerous_action(value)
        if dangerous:
            return False, f"文本包含高危动作: {pattern}", [f"dangerous.text:{pattern}"]
        injection, pattern = has_prompt_injection(value)
        if injection:
            return False, f"文本包含 Prompt 注入: {pattern}", [f"prompt_injection:{pattern}"]
    return True, "", []


def _read_referenced_docs(question_title: str, wiki_root: str) -> List[Tuple[str, str]]:
    docs: List[Tuple[str, str]] = []
    for docs_path in extract_docs_paths(question_title):
        source = resolve_docs_path(docs_path, wiki_root)
        try:
            resolved = source.resolve()
            root = Path(wiki_root).resolve()
            if root not in resolved.parents and resolved != root:
                continue
            if source.is_file() and source.stat().st_size <= 1024 * 1024:
                docs.append((docs_path, source.read_text(encoding="utf-8", errors="ignore")))
        except Exception:
            continue
    return docs


def check_question(question_title: str, permission: Dict[str, Dict[str, List[str]]], wiki_root: str = "llm-wiki") -> Tuple[bool, str, List[str]]:
    text = normalize_text(question_title)
    if not text:
        return False, "question_title is required", ["input.missing_question_title"]

    for docs_path in extract_docs_paths(text):
        ok, reason, matched = check_resource({"kind": "file", "value": docs_path}, permission)
        if not ok:
            return False, reason, matched

    ok, reason, matched = check_permission_commands_in_question(text, permission)
    if not ok:
        return False, reason, matched

    if has_path_traversal(text):
        return False, "问题包含路径穿越", ["path.traversal"]

    command_info_query, _ = is_command_info_query(text)

    dangerous, pattern = has_dangerous_action(text)
    if dangerous and not command_info_query:
        return False, f"问题包含高危动作: {pattern}", [f"dangerous.question:{pattern}"]

    injection, pattern = has_prompt_injection(text)
    if injection:
        return False, f"问题包含 Prompt 注入: {pattern}", [f"prompt_injection.question:{pattern}"]

    secret, pattern = is_secret_query(text)
    if secret and not is_env_info_exception(text):
        return False, f"问题包含敏感信息查询: {pattern}", [f"secret.question:{pattern}"]

    system_path, pattern = is_system_path_query(text)
    if system_path and not is_env_info_exception(text):
        return False, f"问题包含系统路径访问: {pattern}", [f"system_path.question:{pattern}"]

    # If the question delegates to a referenced doc, scan only that referenced doc
    # as untrusted text. This catches hidden task injection without broad file reads.
    for docs_path, content in _read_referenced_docs(text, wiki_root):
        code_result_query = is_code_result_query(text) and is_text_code_path(docs_path)
        dangerous, pattern = has_dangerous_action(content)
        if dangerous and not command_info_query and not code_result_query:
            return False, f"引用文档包含高危动作 {docs_path}: {pattern}", [f"dangerous.document:{pattern}"]
        injection, pattern = has_prompt_injection(content)
        if injection:
            return False, f"引用文档包含 Prompt 注入 {docs_path}: {pattern}", [f"prompt_injection.document:{pattern}"]

    return True, "", []
