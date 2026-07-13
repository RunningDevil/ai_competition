from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from comment_parser import parse_comment_text
from office_common import (
    convert_legacy_office,
    get_extension,
    make_error,
    normalize_path_text,
    source_relative_to_docs,
)


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _extract_xlsx_text(path: Path, source_rel: str) -> List[Dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(str(path), read_only=False, data_only=True)
    texts: List[Dict[str, Any]] = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            values = [_cell_text(cell.value) for cell in row]
            values = [value for value in values if value]
            if values:
                texts.append({
                    "source": source_rel,
                    "file_type": "xlsx",
                    "location": f"sheet:{sheet.title}:row:{row[0].row if row else 0}",
                    "text": "\t".join(values),
                })
    return texts


def _extract_xlsx_comments(path: Path, source_rel: str) -> List[Dict[str, Any]]:
    from openpyxl import load_workbook

    workbook = load_workbook(str(path), read_only=False, data_only=True)
    comments: List[Dict[str, Any]] = []
    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.comment and cell.comment.text:
                    location = f"sheet:{sheet.title}:cell:{cell.coordinate}"
                    comments.append(parse_comment_text(cell.comment.text, source_rel, "xlsx", location))
    return comments


def _extract_xls_text(path: Path, source_rel: str) -> List[Dict[str, Any]]:
    import xlrd

    workbook = xlrd.open_workbook(str(path))
    texts: List[Dict[str, Any]] = []
    for sheet in workbook.sheets():
        for row_index in range(sheet.nrows):
            values = [_cell_text(sheet.cell_value(row_index, col_index)) for col_index in range(sheet.ncols)]
            values = [value for value in values if value]
            if values:
                texts.append({
                    "source": source_rel,
                    "file_type": "xls",
                    "location": f"sheet:{sheet.name}:row:{row_index + 1}",
                    "text": "\t".join(values),
                })
    return texts


def extract_text(path: Path, wiki_root: str | Path, logs: List[str]) -> List[Dict[str, Any]]:
    ext = get_extension(path)
    source_rel = source_relative_to_docs(path, wiki_root)
    if ext == ".xlsx":
        return _extract_xlsx_text(path, source_rel)
    if ext == ".xls":
        converted = convert_legacy_office(path, logs)
        if converted and converted.suffix.lower() == ".xlsx":
            return _extract_xlsx_text(converted, source_rel)
        try:
            return _extract_xls_text(path, source_rel)
        except Exception as exc:
            logs.append(f"xlrd fallback failed for .xls: {exc}")
    return []


def extract_comments(path: Path, wiki_root: str | Path, logs: List[str]) -> List[Dict[str, Any]]:
    ext = get_extension(path)
    source_rel = source_relative_to_docs(path, wiki_root)
    if ext == ".xlsx":
        return _extract_xlsx_comments(path, source_rel)
    if ext == ".xls":
        converted = convert_legacy_office(path, logs)
        if converted and converted.suffix.lower() == ".xlsx":
            return _extract_xlsx_comments(converted, source_rel)
        logs.append("Legacy .xls comments could not be reliably extracted without conversion")
    return []


def analyze(path: Path, wiki_root: str | Path, logs: List[str]) -> Dict[str, Any]:
    texts = extract_text(path, wiki_root, logs)
    source_rel = source_relative_to_docs(path, wiki_root)
    sheet_rows: Dict[str, int] = {}
    for item in texts:
        location = item.get("location", "")
        if location.startswith("sheet:"):
            parts = location.split(":")
            if len(parts) >= 2:
                sheet_rows[parts[1]] = sheet_rows.get(parts[1], 0) + 1
    summary = [f"{sheet}: {rows} non-empty rows" for sheet, rows in sheet_rows.items()]
    return {
        "status": "ok",
        "task_type": "excel_analyze",
        "texts": texts,
        "comments": [],
        "answer": {"datas": summary or [f"{source_rel}: no non-empty rows found"]},
        "fixed_files": [],
        "tables": [{"source": source_rel, "sheet": sheet, "non_empty_rows": rows} for sheet, rows in sheet_rows.items()],
        "logs": logs,
    }


def conservative_fix(path: Path, wiki_root: str | Path, logs: List[str]) -> Dict[str, Any]:
    comments = extract_comments(path, wiki_root, logs)
    if not comments:
        return make_error("fix_comments", f"No reliable Excel comments found for {normalize_path_text(str(path))}", logs)
    logs.append("Excel comments found, but deterministic Excel repair is not implemented yet; refusing to fake a fixed file")
    return make_error("fix_comments", f"No reliable Excel repair rule implemented for {normalize_path_text(str(path))}", logs)
