# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable


def collect_trace(run_log_dir: str | Path, trace_dir: str | Path, run_name: str, summary: Dict[str, Any]) -> Path:
    run_dir = Path(run_log_dir)
    target_dir = Path(trace_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    trace_path = target_dir / f"{run_name}.log"

    with trace_path.open("w", encoding="utf-8") as out:
        out.write("# LLM-WIKI main orchestrator trace\n")
        out.write(json.dumps({"summary": summary}, ensure_ascii=False, indent=2) + "\n")
        for path in sorted(_iter_log_files(run_dir)):
            if path.resolve() == trace_path.resolve():
                continue
            out.write(f"\n## {path.relative_to(run_dir)}\n")
            try:
                out.write(path.read_text(encoding="utf-8", errors="replace"))
            except Exception as exc:
                out.write(f"[trace read failed] {exc}\n")
            if not out.tell():
                out.write("\n")
    return trace_path


def _iter_log_files(run_dir: Path) -> Iterable[Path]:
    for path in run_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".log", ".jsonl", ".json", ".txt"}:
            yield path
