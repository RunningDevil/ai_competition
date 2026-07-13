# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from text_code_common import get_extension, rel_to_docs


ENCODINGS = ("utf-8", "utf-8-sig", "gbk", "gb18030")


def read_text_file(path: str | Path, logs: List[str]) -> Tuple[str, str]:
    file_path = Path(path)
    raw = file_path.read_bytes()
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    logs.append(f"Decoded with replacement characters: {file_path}")
    return raw.decode("utf-8", errors="replace"), "utf-8-replace"


def split_lines(text: str) -> List[str]:
    return text.splitlines()


def extract_text_blocks(path: str | Path, wiki_root: str | Path, logs: List[str], block_size: int = 40) -> List[Dict[str, Any]]:
    text, encoding = read_text_file(path, logs)
    lines = split_lines(text)
    source = rel_to_docs(Path(path), wiki_root)
    ext = get_extension(path)
    blocks: List[Dict[str, Any]] = []
    for start in range(0, len(lines), block_size):
        chunk = lines[start : start + block_size]
        if not any(line.strip() for line in chunk):
            continue
        blocks.append(
            {
                "source": source,
                "file_type": ext,
                "start_line": start + 1,
                "end_line": start + len(chunk),
                "text": "\n".join(chunk),
                "encoding": encoding,
            }
        )
    return blocks
