from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, Dict, List
from xml.etree import ElementTree as ET

from comment_parser import looks_like_comment, parse_comment_text
from office_common import (
    convert_legacy_office,
    extract_printable_text_from_binary,
    get_extension,
    make_error,
    normalize_path_text,
    source_relative_to_docs,
)


A_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def _extract_text_from_shape(shape: Any) -> str:
    if not hasattr(shape, "text"):
        return ""
    return str(shape.text or "").strip()


def _extract_pptx_text(path: Path, source_rel: str) -> List[Dict[str, Any]]:
    from pptx import Presentation

    presentation = Presentation(str(path))
    texts: List[Dict[str, Any]] = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        for shape_index, shape in enumerate(slide.shapes, start=1):
            text = _extract_text_from_shape(shape)
            if text:
                texts.append({
                    "source": source_rel,
                    "file_type": "pptx",
                    "location": f"slide:{slide_index}:shape:{shape_index}",
                    "text": text,
                })
    return texts


def _xml_text(package: zipfile.ZipFile, name: str) -> str:
    try:
        root = ET.fromstring(package.read(name))
    except Exception:
        return ""
    parts = [node.text or "" for node in root.findall(".//a:t", A_NS)]
    return "\n".join(part.strip() for part in parts if part and part.strip())


def _extract_pptx_comments(path: Path, source_rel: str) -> List[Dict[str, Any]]:
    comments: List[Dict[str, Any]] = []
    with zipfile.ZipFile(path) as package:
        for name in package.namelist():
            lowered = name.lower()
            if not name.endswith(".xml"):
                continue
            if "comment" in lowered or "notesSlides" in name:
                text = _xml_text(package, name)
                if text and looks_like_comment(text):
                    comments.append(parse_comment_text(text, source_rel, "pptx", name))
    return comments


def extract_text(path: Path, wiki_root: str | Path, logs: List[str]) -> List[Dict[str, Any]]:
    ext = get_extension(path)
    source_rel = source_relative_to_docs(path, wiki_root)
    if ext == ".pptx":
        return _extract_pptx_text(path, source_rel)
    if ext == ".ppt":
        converted = convert_legacy_office(path, logs)
        if converted and converted.suffix.lower() == ".pptx":
            return _extract_pptx_text(converted, source_rel)
        fallback = extract_printable_text_from_binary(path)
        return [{"source": source_rel, "file_type": "ppt", "location": "legacy:fallback_text", "text": fallback}] if fallback else []
    return []


def extract_comments(path: Path, wiki_root: str | Path, logs: List[str]) -> List[Dict[str, Any]]:
    ext = get_extension(path)
    source_rel = source_relative_to_docs(path, wiki_root)
    if ext == ".pptx":
        return _extract_pptx_comments(path, source_rel)
    if ext == ".ppt":
        converted = convert_legacy_office(path, logs)
        if converted and converted.suffix.lower() == ".pptx":
            return _extract_pptx_comments(converted, source_rel)
        fallback = extract_printable_text_from_binary(path)
        if looks_like_comment(fallback):
            return [parse_comment_text(fallback, source_rel, "ppt", "legacy:fallback_text")]
        logs.append("Legacy .ppt comments could not be reliably extracted")
    return []


def conservative_fix(path: Path, wiki_root: str | Path, logs: List[str]) -> Dict[str, Any]:
    comments = extract_comments(path, wiki_root, logs)
    if not comments:
        return make_error("fix_comments", f"No reliable PowerPoint comments found for {normalize_path_text(str(path))}", logs)
    logs.append("PowerPoint comments found, but deterministic PowerPoint repair is not implemented yet; refusing to fake a fixed file")
    return make_error("fix_comments", f"No reliable PowerPoint repair rule implemented for {normalize_path_text(str(path))}", logs)
