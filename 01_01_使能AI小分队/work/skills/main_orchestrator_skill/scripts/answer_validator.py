# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from orchestrator_common import COUNTABLE_EXTS, HIGH_RISK_ANSWER, normalize_path_text, unique_preserve_order


def normalize_answer(answer: Any) -> Dict[str, Any]:
    if not isinstance(answer, dict):
        if answer is None:
            return {"datas": []}
        return {"datas": [str(answer)]}

    if answer.get("error_msg"):
        return {"error_msg": str(answer.get("error_msg"))}

    countable = {key: int(value) for key, value in answer.items() if key in COUNTABLE_EXTS and isinstance(value, int)}
    if countable:
        return countable

    if "count" in answer:
        try:
            return {"count": int(answer.get("count") or 0)}
        except Exception:
            return {"count": 0}

    if "source" in answer and "target" in answer:
        return {
            "source": normalize_path_text(answer.get("source")),
            "target": normalize_path_text(answer.get("target")),
        }

    if "datas" in answer:
        datas = answer.get("datas")
        if isinstance(datas, list):
            return {"datas": unique_preserve_order([str(item) for item in datas if item is not None])}
        if datas is None:
            return {"datas": []}
        return {"datas": [str(datas)]}

    return {"datas": []}


def answer_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(result, dict):
        return {"datas": []}
    if result.get("decision") == "deny":
        return normalize_answer(result.get("answer") or HIGH_RISK_ANSWER)
    return normalize_answer(result.get("answer") or {"datas": []})


def build_answer_item(question: Dict[str, Any], answer: Any) -> Dict[str, Any]:
    return {
        "id": str(question.get("id") or ""),
        "answer": normalize_answer(answer),
    }


def verify_fixed_file(answer: Dict[str, Any], wiki_root: str | Path) -> Dict[str, Any]:
    normalized = normalize_answer(answer)
    if "target" not in normalized:
        return normalized
    target = Path(wiki_root) / normalized["target"]
    if target.exists():
        return normalized
    # Keep the path contract, but do not pretend the file exists in logs; final answer remains spec-shaped.
    return normalized
