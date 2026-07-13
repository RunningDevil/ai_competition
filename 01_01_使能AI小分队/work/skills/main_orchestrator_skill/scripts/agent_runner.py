# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from orchestrator_common import append_jsonl, read_json_file, write_json_file


class AgentRunner:
    def __init__(self, project_root: Path, run_log_dir: Path, timeout: int = 300) -> None:
        self.project_root = project_root
        self.run_log_dir = run_log_dir
        self.timeout = timeout
        self.middleware_dir = run_log_dir / "middleware"
        self.middleware_dir.mkdir(parents=True, exist_ok=True)
        self.counter = 0

    def script_path(self, skill_name: str, script_name: str) -> Path:
        return self.project_root / "work" / "skills" / skill_name / "scripts" / script_name

    def run_cli(self, label: str, script: Path, payload: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
        self.counter += 1
        safe_label = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in label)
        input_path = self.middleware_dir / f"{self.counter:03d}_{safe_label}_payload.json"
        output_path = self.middleware_dir / f"{self.counter:03d}_{safe_label}_result.json"
        write_json_file(input_path, payload)

        record: Dict[str, Any] = {
            "label": label,
            "script": str(script),
            "payload_file": str(input_path),
            "result_file": str(output_path),
        }

        if not script.exists():
            result = {
                "status": "error",
                "reason": f"script not found: {script}",
                "answer": {"datas": []},
                "logs": [],
            }
            write_json_file(output_path, result)
            record["status"] = "error"
            record["reason"] = result["reason"]
            append_jsonl(self.run_log_dir / "main_orchestrator_agent_result.jsonl", record)
            return result

        cmd = [sys.executable, str(script), "--input-file", str(input_path), "--output-file", str(output_path)]
        try:
            completed = subprocess.run(
                cmd,
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout or self.timeout,
            )
            record["returncode"] = completed.returncode
            record["stdout"] = completed.stdout[-4000:]
            record["stderr"] = completed.stderr[-4000:]
            if output_path.exists():
                result = read_json_file(output_path)
            else:
                result = json.loads(completed.stdout) if completed.stdout.strip().startswith("{") else {
                    "status": "error",
                    "reason": "agent produced no JSON output file",
                    "answer": {"datas": []},
                    "logs": [],
                }
            if completed.returncode != 0 and result.get("status") != "ok":
                result.setdefault("reason", completed.stderr.strip() or f"returncode={completed.returncode}")
            record["status"] = result.get("status")
            record["reason"] = result.get("reason") or result.get("error_msg")
        except Exception as exc:
            result = {
                "status": "error",
                "reason": str(exc),
                "answer": {"datas": []},
                "logs": [],
            }
            write_json_file(output_path, result)
            record["status"] = "error"
            record["reason"] = str(exc)

        append_jsonl(self.run_log_dir / "main_orchestrator_agent_result.jsonl", record)
        return result
