# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

from orchestrator_common import normalize_text, write_json_file


def _extract_json_array(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("["):
        return stripped
    match = re.search(r"\[[\s\S]*\]", stripped)
    if not match:
        raise ValueError("question file does not contain a JSON array")
    return match.group(0)


def load_questions(question_file: str | Path) -> List[Dict[str, Any]]:
    text = Path(question_file).read_text(encoding="utf-8-sig")
    data = json.loads(_extract_json_array(text))
    if not isinstance(data, list):
        raise ValueError("question file must contain a JSON array")
    questions: List[Dict[str, Any]] = []
    for index, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"question item #{index} is not an object")
        qid = normalize_text(item.get("id")) or f"question-{index}"
        title = normalize_text(item.get("title"))
        questions.append({"id": qid, "title": title, "level": normalize_text(item.get("level")), "raw": item})
    return questions


def derive_output_file(question_file: str | Path, wiki_root: str | Path) -> Path:
    question_path = Path(question_file)
    stem = question_path.stem
    return Path(wiki_root) / "output" / f"{stem}-answer.md"


def write_answers(output_file: str | Path, answers: List[Dict[str, Any]]) -> None:
    write_json_file(output_file, answers)
