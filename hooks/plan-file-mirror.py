#!/usr/bin/env python3
"""Mirror repo plan documents into Claude Code's active plan-mode file."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _load_hook_input() -> dict[str, Any]:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except Exception:
        return False


def _read_latest_plan_state(transcript_path: Path) -> tuple[Path | None, bool]:
    plan_path: Path | None = None
    in_plan_mode = False

    try:
        with transcript_path.open("r", encoding="utf-8") as transcript:
            for line in transcript:
                try:
                    event = json.loads(line)
                except Exception:
                    continue

                attachment = event.get("attachment")
                if isinstance(attachment, dict):
                    attachment_type = attachment.get("type")
                    if attachment_type == "plan_mode":
                        raw_plan_path = attachment.get("planFilePath")
                        if isinstance(raw_plan_path, str) and raw_plan_path:
                            plan_path = Path(raw_plan_path).expanduser()
                        in_plan_mode = True
                    elif attachment_type == "plan_mode_exit":
                        in_plan_mode = False

                permission_mode = event.get("permissionMode")
                if permission_mode == "plan":
                    in_plan_mode = True
                elif isinstance(permission_mode, str) and permission_mode:
                    in_plan_mode = False

                if event.get("type") == "permission-mode":
                    mode = event.get("permissionMode")
                    if mode == "plan":
                        in_plan_mode = True
                    elif isinstance(mode, str) and mode:
                        in_plan_mode = False
    except Exception:
        return None, False

    return plan_path, in_plan_mode


def _cwd_from_hook(data: dict[str, Any]) -> Path | None:
    raw = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(raw).expanduser() if isinstance(raw, str) and raw else None


def _is_allowed_source(path: Path, cwd: Path | None) -> bool:
    if path.suffix.lower() not in {".md", ".markdown"}:
        return False
    if cwd is None:
        return False
    return _is_under(path, cwd / "docs" / "superpowers" / "plans")


def _looks_like_plan(content: str) -> bool:
    if len(content.strip()) < 80:
        return False
    lower = content.lower()
    markers = ("# ", "## ", "plan", "implementation", "task", "- [ ]")
    return sum(1 for marker in markers if marker in lower) >= 3


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    data = _load_hook_input()
    if data.get("hook_event_name") != "PostToolUse":
        return 0
    if data.get("tool_name") != "Write":
        return 0

    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0

    tool_response = data.get("tool_response")
    if not isinstance(tool_response, dict):
        tool_response = {}

    source_raw = tool_input.get("file_path") or tool_response.get("filePath")
    if not isinstance(source_raw, str):
        return 0

    source_path = Path(source_raw).expanduser()
    if not _is_allowed_source(source_path, _cwd_from_hook(data)):
        return 0

    content = ""
    try:
        if source_path.exists():
            content = source_path.read_text(encoding="utf-8")
    except Exception:
        content = ""
    if not content:
        raw_content = tool_input.get("content")
        if isinstance(raw_content, str):
            content = raw_content

    if not _looks_like_plan(content):
        return 0

    transcript_raw = data.get("transcript_path")
    if not isinstance(transcript_raw, str) or not transcript_raw:
        return 0

    plan_path, in_plan_mode = _read_latest_plan_state(Path(transcript_raw).expanduser())
    if plan_path is None or not in_plan_mode:
        return 0

    plans_root = Path.home() / ".claude" / "plans"
    if not _is_under(plan_path, plans_root):
        return 0

    current = plan_path.read_text(encoding="utf-8") if plan_path.exists() else None
    if current != content:
        _write_atomic(plan_path, content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
