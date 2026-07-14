# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any, Dict, List

from qa_common import clamp, make_base_result, make_error, preview_text, unique_preserve_order, write_code_reasoning_task


COMMAND_START_RE = re.compile(
    r"^\s*(?:[$>#]\s*|PS>\s*|C:\\>\s*)?"
    r"(?:sudo\s+)?"
    r"(?:ssh|scp|sftp|gsql|psql|mysql|sqlcmd|kubectl|docker(?:-compose)?|curl|wget|python3?|java|mvn|gradle|npm|yarn|pnpm|git|tar|unzip|zip|systemctl|journalctl|grep|find|cat|cd|ls|rm|rmdir|del|remove-item|kill|pkill|taskkill|chmod|chown|export|source|bash|sh|powershell|cmd)\b"
    r"|^\s*(?:[$>#]\s*)?[./~A-Za-z0-9_-]+\.(?:sh|cmd|bat|ps1)\b",
    re.IGNORECASE,
)
COMMAND_ANY_RE = re.compile(
    r"(?:sudo\s+)?(?:ssh|scp|sftp|gsql|psql|mysql|sqlcmd|kubectl|docker(?:-compose)?|curl|wget|python3?|java|mvn|gradle|npm|yarn|pnpm|git|tar|unzip|zip|systemctl|journalctl|grep|find|cat|cd|ls|rm|rmdir|del|remove-item|kill|pkill|taskkill|chmod|chown|export|source|bash|sh|powershell|cmd)\b[^`。；\n\r]*",
    re.IGNORECASE,
)

COMMAND_MARKERS = (" -", " --", "=", "://", "|", "&&", ";", "\\", "$(", "`")
COMMAND_QUERY_IGNORE = {
    "命令",
    "指令",
    "命令行",
    "语句",
    "shell",
    "脚本",
    "控制台",
    "终端",
    "客户端",
    "连接",
    "登录",
    "访问",
    "账号",
    "用户",
    "用户名",
    "user",
    "login",
    "db",
    "database",
    "数据库",
}


def _line_score(line: str, query: Dict[str, Any]) -> float:
    score = 0.0
    lower = line.lower()
    for keyword in query.get("keywords") or []:
        keyword_text = str(keyword)
        if keyword_text and keyword_text.lower() in lower:
            score += 1.5 if len(keyword_text) <= 3 else 3.0
    for ip in query.get("ips") or []:
        if ip in line:
            score += 5.0
    if query.get("intent") == "environment_info" and any(word in line for word in ("密码", "password", "pwd", "账号", "用户")):
        score += 3.0
    if query.get("intent") == "command_info" and any(mark in line for mark in ("-", "--", "=", "jdbc", "ssh", "psql", "gsql")):
        score += 2.0
    return score


def _best_lines(text: str, query: Dict[str, Any], per_block: int = 2) -> List[str]:
    parts = [part.strip() for part in re.split(r"[\r\n]+|(?<=[。；;])", text or "") if part.strip()]
    if not parts:
        return []
    scored = [(part, _line_score(part, query)) for part in parts]
    positive = [item for item in scored if item[1] > 0]
    selected = positive or scored[:per_block]
    selected.sort(key=lambda item: -item[1])
    return [preview_text(item[0], 500) for item in selected[:per_block]]


def _strip_prompt(line: str) -> str:
    return re.sub(r"^\s*(?:[$>#]\s*|PS>\s*|C:\\>\s*)", "", line).rstrip()


def _looks_like_command_line(line: str) -> bool:
    stripped = _strip_prompt(line).strip()
    if not stripped:
        return False
    if "```" in stripped:
        return False
    if COMMAND_START_RE.search(stripped):
        return True
    if any(marker in stripped for marker in COMMAND_MARKERS) and not re.search(r"[。；，：]", stripped):
        return True
    return False


def _looks_like_continuation(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("-", "--", "|", "&&")):
        return True
    if re.match(r"^[A-Za-z0-9_.-]+=.+", stripped):
        return True
    if re.match(r"^[A-Za-z0-9_/-]+:[A-Za-z0-9_./:-]+", stripped):
        return True
    return line[:1].isspace() and not re.search(r"[。；。]", stripped)


def _fenced_command_blocks(text: str) -> List[str]:
    blocks = []
    for match in re.finditer(r"```[A-Za-z0-9_-]*\s*(.*?)```", text or "", flags=re.DOTALL):
        block = match.group(1).strip()
        if not block:
            continue
        lines = [line for line in block.splitlines() if line.strip()]
        if any(_looks_like_command_line(line) for line in lines):
            blocks.append("\n".join(_strip_prompt(line) for line in lines))
    return blocks


def _embedded_command_blocks(text: str) -> List[str]:
    blocks = []
    for line in (text or "").splitlines() or [text or ""]:
        for match in COMMAND_ANY_RE.finditer(line):
            command = match.group(0).strip()
            command = command.strip("`").strip()
            first_token = command.split(None, 1)[0] if command.split() else ""
            if re.search(r"\.(?:pdf|md|txt|docx?|pptx?|xlsx?)$", first_token, flags=re.IGNORECASE):
                continue
            if command and _looks_like_command_line(command):
                blocks.append(command)
    return blocks


def _inline_command_blocks(text: str) -> List[str]:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    blocks: List[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _looks_like_command_line(line):
            index += 1
            continue
        block = [_strip_prompt(line)]
        continuation_expected = line.rstrip().endswith("\\")
        index += 1
        while index < len(lines):
            next_line = lines[index]
            if not next_line.strip():
                break
            if continuation_expected or _looks_like_continuation(next_line):
                block.append(_strip_prompt(next_line))
                continuation_expected = next_line.rstrip().endswith("\\")
                index += 1
                continue
            break
        blocks.append("\n".join(item for item in block if item.strip()))
    return blocks


def _command_block_score(block: str, query: Dict[str, Any]) -> float:
    score = 0.0
    lower = block.lower()
    for keyword in query.get("keywords") or []:
        keyword_text = str(keyword or "")
        if keyword_text and keyword_text.lower() in lower:
            score += 3.0 if len(keyword_text) >= 3 else 1.5
    if any(command in lower for command in ("ssh", "gsql", "psql", "mysql", "kubectl", "docker", "curl", "wget", "rm", "kill", "chmod")):
        score += 5.0
    if "\n" in block:
        score += 2.0
    if any(marker in block for marker in (" -", " --", "=", "://")):
        score += 2.0
    return score


def _command_query_match_score(block: str, query: Dict[str, Any]) -> float:
    score = 0.0
    lower = block.lower()
    for keyword in query.get("keywords") or []:
        keyword_text = str(keyword or "").strip()
        if len(keyword_text) < 2:
            continue
        if keyword_text.lower() in COMMAND_QUERY_IGNORE:
            continue
        if keyword_text.lower() in lower:
            score += 2.0 if len(keyword_text) <= 3 else 4.0
    return score


def _build_command_answer(query: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    candidates: List[tuple[str, float, float]] = []
    for item in evidence:
        text = str(item.get("text") or "")
        fenced_blocks = _fenced_command_blocks(text)
        text_without_fences = re.sub(r"```[A-Za-z0-9_-]*\s*.*?```", " ", text or "", flags=re.DOTALL)
        for block in fenced_blocks + _inline_command_blocks(text_without_fences) + _embedded_command_blocks(text_without_fences):
            block = preview_text(block.strip(), 900)
            if block:
                candidates.append((block, _command_block_score(block, query), _command_query_match_score(block, query)))
    if not candidates:
        return _build_text_answer(query, evidence)
    matched = [item for item in candidates if item[2] > 0]
    if matched:
        candidates = matched
    candidates.sort(key=lambda item: (-item[2], -item[1]))
    return {"datas": unique_preserve_order([item[0] for item in candidates])[:10]}


def _evidence_preview(evidence: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for item in evidence:
        result.append(
            {
                "source": item.get("source", ""),
                "file_type": item.get("file_type", ""),
                "kind": item.get("kind", ""),
                "location": item.get("location", ""),
                "score": item.get("score", 0),
                "text": preview_text(item.get("text"), 220),
                "match_reasons": item.get("match_reasons", []),
            }
        )
    return result


def _confidence(evidence: List[Dict[str, Any]]) -> float:
    if not evidence:
        return 0.0
    top_score = float(evidence[0].get("score") or 0)
    return round(clamp(top_score / 60.0, 0.25, 0.98), 2)


def _build_path_answer(query: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    content_evidence = [item for item in evidence if item.get("kind") != "metadata"] or evidence
    paths = []
    for item in content_evidence:
        source = str(item.get("source") or "")
        if source.startswith("docs/"):
            paths.append(source)
    paths = unique_preserve_order(paths)
    if query.get("expects_count"):
        return {"count": len(paths)}
    return {"datas": paths}


def _build_text_answer(query: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    datas: List[str] = []
    for item in evidence:
        text = str(item.get("text") or "")
        datas.extend(_best_lines(text, query))
    return {"datas": unique_preserve_order(datas)[:10]}


def _query_users(query: Dict[str, Any]) -> List[str]:
    users: List[str] = []
    for keyword in query.get("keywords") or []:
        text = str(keyword or "").strip()
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{2,}", text) and any(mark in text.lower() for mark in ("user", "op", "admin", "root", "svc", "deploy")):
            users.append(text)
    return unique_preserve_order(users)


def _build_environment_answer(query: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
    datas: List[str] = []
    users = _query_users(query)
    ips = query.get("ips") or []
    for item in evidence:
        text = str(item.get("text") or "")
        lines = _best_lines(text, query, per_block=4)
        for line in lines:
            if ips and not any(ip in line for ip in ips):
                continue
            for user in users:
                match = re.search(rf"(?<![A-Za-z0-9_]){re.escape(user)}[/：:]\s*([^\s/，,；;]+)", line)
                if match:
                    datas.append(match.group(1).strip())
            if not users:
                secret_matches = re.findall(r"(?:密码|password|pwd)\s*[:：=]\s*([^\s，,；;]+)", line, flags=re.IGNORECASE)
                datas.extend(item.strip() for item in secret_matches)
    return {"datas": unique_preserve_order(datas)[:10]}


def build_answer(payload: Dict[str, Any], query: Dict[str, Any], evidence: List[Dict[str, Any]], logs: List[str] | None = None) -> Dict[str, Any]:
    logs = logs if logs is not None else []
    task_type = str(payload.get("task_type") or query.get("task_type") or "answer_from_context")
    if not evidence:
        logs.append("No reliable evidence found")
        return make_error(task_type, "no reliable evidence", logs)

    result = make_base_result(task_type)
    intent = query.get("intent")
    if (task_type == "answer_code_static_question" or intent == "code_static_question") and query.get("expects_code_execution_result"):
        task_path = write_code_reasoning_task(payload, query, evidence, logs)
        result["status"] = "code_reasoning_required"
        result["answer"] = {"datas": []}
        result["evidence"] = _evidence_preview(evidence)
        result["confidence"] = _confidence(evidence)
        result["logs"] = logs
        if task_path:
            result["code_reasoning_tasks"] = [task_path]
        result["reason"] = "代码执行结果需要由外层 CodeAgent 按 INSTRUCTION.md 使用模型能力静态推演"
        return result

    if task_type == "answer_file_content_paths" or intent == "file_content_paths":
        answer = _build_path_answer(query, evidence)
    elif task_type == "answer_environment_info" or intent == "environment_info":
        answer = _build_environment_answer(query, evidence)
        if answer.get("datas") == []:
            answer = _build_text_answer(query, evidence)
    elif task_type == "answer_command_info" or intent == "command_info":
        answer = _build_command_answer(query, evidence)
    elif task_type == "answer_excel_summary" or intent == "excel_summary":
        table_first = sorted(evidence, key=lambda item: 0 if item.get("kind") == "table" else 1)
        answer = _build_text_answer(query, table_first)
    elif task_type == "answer_code_static_question" or intent == "code_static_question":
        risk_first = sorted(evidence, key=lambda item: 0 if item.get("kind") == "risk" else 1)
        answer = _build_text_answer(query, risk_first)
    else:
        answer = _build_text_answer(query, evidence)

    if answer.get("datas") == []:
        logs.append("Evidence existed but no answer text could be extracted")
        return make_error(task_type, "no reliable answer text", logs)

    result["answer"] = answer
    result["evidence"] = _evidence_preview(evidence)
    result["confidence"] = _confidence(evidence)
    result["logs"] = logs
    return result
