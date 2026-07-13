# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List

from qa_common import get_candidate_path, get_extension, normalize_path_text, normalize_text


def _make_block(
    source: Any,
    file_type: Any,
    kind: str,
    text: Any,
    location: Any = "",
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    source_text = normalize_path_text(source)
    file_type_text = normalize_text(file_type).lower().lstrip(".") or get_extension(source_text)
    return {
        "source": source_text,
        "file_type": file_type_text,
        "kind": normalize_text(kind) or "text",
        "location": normalize_text(location),
        "text": normalize_text(text),
        "metadata": metadata or {},
    }


def _block_from_context(item: Any) -> Dict[str, Any] | None:
    if isinstance(item, str):
        text = normalize_text(item)
        return _make_block("", "", "text", text) if text else None
    if not isinstance(item, dict):
        return None

    source = item.get("source") or item.get("path") or item.get("file") or item.get("relative_path")
    text = (
        item.get("text")
        or item.get("raw_text")
        or item.get("content")
        or item.get("summary")
        or item.get("todo")
        or item.get("value")
    )
    if text is None and item.get("datas") is not None:
        text = "\n".join(str(value) for value in item.get("datas") or [])
    if text is None:
        return None

    kind = item.get("kind") or item.get("type") or item.get("block_type") or "text"
    metadata = dict(item.get("metadata") or {})
    for key in ("structured", "to", "end_date", "sheet", "risk_level", "score"):
        if key in item and key not in metadata:
            metadata[key] = item[key]
    return _make_block(
        source,
        item.get("file_type") or item.get("extension"),
        str(kind),
        text,
        item.get("location") or item.get("range") or item.get("cell") or "",
        metadata,
    )


def _blocks_from_items(items: Iterable[Any], kind: str) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            block = _make_block("", "", kind, item)
        else:
            source = item.get("source") or item.get("path") or item.get("relative_path")
            text = (
                item.get("text")
                or item.get("raw_text")
                or item.get("todo")
                or item.get("summary")
                or item.get("message")
                or item.get("description")
            )
            if text is None:
                text = json.dumps(item, ensure_ascii=False, sort_keys=True)
            block = _make_block(
                source,
                item.get("file_type") or item.get("extension"),
                kind,
                text,
                item.get("location") or item.get("cell") or item.get("range") or "",
                {k: v for k, v in item.items() if k not in {"text", "raw_text", "todo", "summary"}},
            )
        if block["text"]:
            blocks.append(block)
    return blocks


def _blocks_from_result(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    blocks.extend(_blocks_from_items(result.get("texts") or [], "text"))
    blocks.extend(_blocks_from_items(result.get("comments") or [], "comment"))
    blocks.extend(_blocks_from_items(result.get("todos") or [], "todo"))
    blocks.extend(_blocks_from_items(result.get("risks") or [], "risk"))
    blocks.extend(_blocks_from_items(result.get("tables") or [], "table"))
    return blocks


def normalize_context(payload: Dict[str, Any], logs: List[str] | None = None) -> List[Dict[str, Any]]:
    logs = logs if logs is not None else []
    blocks: List[Dict[str, Any]] = []

    for item in payload.get("context_blocks") or []:
        block = _block_from_context(item)
        if block and block["text"]:
            blocks.append(block)

    for key in ("texts", "comments", "todos", "risks", "tables"):
        if payload.get(key):
            kind = "todo" if key == "todos" else key[:-1]
            blocks.extend(_blocks_from_items(payload.get(key) or [], kind))

    for key in ("office_result", "text_code_result"):
        result = payload.get(key)
        if isinstance(result, dict):
            blocks.extend(_blocks_from_result(result))

    for result in payload.get("agent_results") or []:
        if isinstance(result, dict):
            blocks.extend(_blocks_from_result(result))

    for candidate in payload.get("candidate_files") or []:
        path = get_candidate_path(candidate)
        if not path:
            continue
        ext = ""
        metadata: Dict[str, Any] = {}
        if isinstance(candidate, dict):
            ext = normalize_text(candidate.get("extension") or candidate.get("file_type"))
            metadata = dict(candidate)
        block_text = " ".join(value for value in [path, ext, normalize_text(metadata.get("name"))] if value)
        blocks.append(_make_block(path, ext or get_extension(path), "metadata", block_text, "", metadata))

    index_summary = payload.get("index_summary")
    if index_summary:
        blocks.append(_make_block("", "", "index_summary", json.dumps(index_summary, ensure_ascii=False, sort_keys=True)))

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for block in blocks:
        key = (block["source"], block["kind"], block["location"], block["text"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(block)

    logs.append(f"Normalized {len(deduped)} context blocks")
    return deduped
