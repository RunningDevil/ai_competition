from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple
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


WORD_NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
}


def _text_from_xml_element(element: ET.Element) -> str:
    parts = [node.text or "" for node in element.findall(".//w:t", WORD_NS)]
    return "".join(parts).strip()


def _extract_docx_text(path: Path, source_rel: str) -> List[Dict[str, Any]]:
    from docx import Document

    doc = Document(str(path))
    texts: List[Dict[str, Any]] = []
    for index, paragraph in enumerate(doc.paragraphs, start=1):
        text = paragraph.text.strip()
        if text:
            texts.append({"source": source_rel, "file_type": "docx", "location": f"paragraph:{index}", "text": text})
    for table_index, table in enumerate(doc.tables, start=1):
        for row_index, row in enumerate(table.rows, start=1):
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                texts.append({
                    "source": source_rel,
                    "file_type": "docx",
                    "location": f"table:{table_index}:row:{row_index}",
                    "text": "\t".join(cells),
                })
    return texts


def _extract_docx_comments(path: Path, source_rel: str) -> List[Dict[str, Any]]:
    comments: List[Dict[str, Any]] = []
    with zipfile.ZipFile(path) as package:
        names = set(package.namelist())
        comment_files = [name for name in names if name.startswith("word/") and "comment" in name.lower() and name.endswith(".xml")]
        for comment_file in comment_files:
            root = ET.fromstring(package.read(comment_file))
            for index, comment in enumerate(root.findall(".//w:comment", WORD_NS), start=1):
                text = _text_from_xml_element(comment)
                if text:
                    comments.append(parse_comment_text(text, source_rel, "docx", f"{comment_file}:comment:{index}"))
    return comments


def extract_text(path: Path, wiki_root: str | Path, logs: List[str]) -> List[Dict[str, Any]]:
    ext = get_extension(path)
    source_rel = source_relative_to_docs(path, wiki_root)
    if ext == ".docx":
        return _extract_docx_text(path, source_rel)
    if ext == ".doc":
        converted = convert_legacy_office(path, logs)
        if converted and converted.suffix.lower() == ".docx":
            return _extract_docx_text(converted, source_rel)
        fallback = extract_printable_text_from_binary(path)
        return [{"source": source_rel, "file_type": "doc", "location": "legacy:fallback_text", "text": fallback}] if fallback else []
    return []


def extract_comments(path: Path, wiki_root: str | Path, logs: List[str]) -> List[Dict[str, Any]]:
    ext = get_extension(path)
    source_rel = source_relative_to_docs(path, wiki_root)
    if ext == ".docx":
        return _extract_docx_comments(path, source_rel)
    if ext == ".doc":
        converted = convert_legacy_office(path, logs)
        if converted and converted.suffix.lower() == ".docx":
            return _extract_docx_comments(converted, source_rel)
        fallback = extract_printable_text_from_binary(path)
        if looks_like_comment(fallback):
            return [parse_comment_text(fallback, source_rel, "doc", "legacy:fallback_text")]
        logs.append("Legacy .doc comments could not be reliably extracted")
    return []


def conservative_fix(path: Path, wiki_root: str | Path, logs: List[str]) -> Dict[str, Any]:
    comments = extract_comments(path, wiki_root, logs)
    if not comments:
        return make_error("fix_comments", f"No reliable Word comments found for {normalize_path_text(str(path))}", logs)
    logs.append("Word comments found, but deterministic Word repair is not implemented yet; refusing to fake a fixed file")
    return make_error("fix_comments", f"No reliable Word repair rule implemented for {normalize_path_text(str(path))}", logs)
