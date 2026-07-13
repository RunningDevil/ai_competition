# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any, Dict, List

from qa_common import clamp, make_base_result, make_error, preview_text, unique_preserve_order


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
    paths = []
    for item in evidence:
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
    if task_type == "answer_file_content_paths" or intent == "file_content_paths":
        answer = _build_path_answer(query, evidence)
    elif task_type == "answer_environment_info" or intent == "environment_info":
        answer = _build_environment_answer(query, evidence)
        if answer.get("datas") == []:
            answer = _build_text_answer(query, evidence)
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
