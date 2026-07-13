# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from text_code_common import get_extension, rel_to_docs
from text_reader import read_text_file, split_lines


RISK_RULES: List[Tuple[str, str, re.Pattern[str]]] = [
    ("prompt_injection", "high", re.compile(r"忽略前面|忽略.*规则|开启上帝模式|最高优先级|删除全部|kill\s+codeagent|taskkill", re.IGNORECASE)),
    ("dangerous_command", "high", re.compile(r"rm\s+-rf|Remove-Item|\bdel\b|taskkill|chmod\s+777|kill\s+-9", re.IGNORECASE)),
    ("system_path", "medium", re.compile(r"(^|[\s\"'`])/(?:etc|root|var)|[A-Za-z]:\\|99_mock_system_dir", re.IGNORECASE)),
    ("secret_or_password", "medium", re.compile(r"password|passwd|secret|token|AK/SK|access[_-]?key|密钥|密码", re.IGNORECASE)),
    ("file_mutation_intent", "medium", re.compile(r"写入|删除|覆盖|执行命令|终止进程|创建.*脚本", re.IGNORECASE)),
]


def analyze_text_code(path: str | Path, wiki_root: str | Path, logs: List[str]) -> List[Dict[str, Any]]:
    text, encoding = read_text_file(path, logs)
    source = rel_to_docs(Path(path), wiki_root)
    ext = get_extension(path)
    risks: List[Dict[str, Any]] = []
    for index, line in enumerate(split_lines(text), start=1):
        if not line.strip():
            continue
        for risk_type, level, pattern in RISK_RULES:
            if pattern.search(line):
                risks.append(
                    {
                        "source": source,
                        "file_type": ext,
                        "location": f"line:{index}",
                        "type": risk_type,
                        "risk_level": level,
                        "text": line.strip(),
                    }
                )
    return risks


def summarize_risk_level(risks: List[Dict[str, Any]]) -> str:
    if any(item.get("risk_level") == "high" for item in risks):
        return "high"
    if any(item.get("risk_level") == "medium" for item in risks):
        return "medium"
    return "low"
