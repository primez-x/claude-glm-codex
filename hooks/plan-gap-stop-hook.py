#!/usr/bin/env python3
"""Enforce active Claude plan implementation goals before stopping."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BLOCK_REASON = """Active Claude plan implementation goal is not complete.

Continue in this same session. Before stopping, complete the implementation gap loop and end with:

Plan Gap Check
Plan recovered: summarize the accepted plan as concrete commitments.
Gap checklist: compare those commitments against the actual diff, code paths, tests, docs, config, and generated artifacts.
Fixes applied: list any in-scope gaps you fixed, or state none remained.
Verification: list the focused checks you ran and their result.
Remaining risk: state any residual risk or none known.

If the goal is genuinely blocked, end with:

Goal blocked
Blocking condition: the concrete blocker.
Needed from user: the specific input or external state needed."""


def _load_hook_input() -> dict[str, Any]:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _goal_dir() -> Path:
    configured = os.environ.get("CLAUDE_GOAL_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".claude" / "goals"


def _safe_state_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())
    safe = safe.strip("._-")
    if safe:
        return safe[:120]
    digest = hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"session-{digest}"


def _state_identity(data: dict[str, Any]) -> tuple[str, str]:
    session_id = str(data.get("session_id") or "").strip()
    if session_id:
        return _safe_state_name(session_id), session_id

    seed = str(data.get("transcript_path") or data.get("cwd") or "unknown-session")
    digest = hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]
    fallback = f"session-{digest}"
    return fallback, ""


def _state_path(data: dict[str, Any]) -> Path:
    key, _ = _state_identity(data)
    return _goal_dir() / f"{key}.json"


def _read_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        tmp_path.chmod(0o600)
    except OSError:
        pass
    os.replace(tmp_path, path)


def _update_state(path: Path, state: dict[str, Any], status: str | None = None) -> None:
    if status is not None:
        state["status"] = status
    state["updated_at"] = _now()
    _write_state(path, state)


def _assistant_text_from_event(event: dict[str, Any]) -> list[str]:
    message = event.get("message")
    if isinstance(message, dict):
        role = message.get("role")
        content = message.get("content")
    else:
        role = event.get("role")
        content = event.get("content")

    if role != "assistant":
        return []

    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []

    texts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
        elif isinstance(block, str):
            texts.append(block)
    return texts


def _latest_assistant_text(transcript_path: str) -> str:
    if not transcript_path:
        return ""

    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return ""

    recent_texts: deque[str] = deque(maxlen=20)
    try:
        with path.open("r", encoding="utf-8") as transcript:
            for line in transcript:
                if "assistant" not in line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                for text in _assistant_text_from_event(event):
                    if text.strip():
                        recent_texts.append(text)
    except Exception:
        return ""

    return "\n\n".join(recent_texts)


def _has_all(text: str, fragments: tuple[str, ...]) -> bool:
    lowered = text.casefold()
    return all(fragment in lowered for fragment in fragments)


def _completion_status(text: str) -> str | None:
    lowered = text.casefold()
    if _has_all(
        text,
        (
            "plan gap check",
            "plan recovered",
            "gap checklist",
            "fixes applied",
            "verification",
            "remaining risk",
        ),
    ):
        return "complete"

    is_blocked = "goal blocked" in lowered or re.search(r"(^|\n)\s*blocked\b", lowered)
    has_blocker = "blocking condition" in lowered or "cannot proceed" in lowered
    asks_user = "needed from user" in lowered or "waiting for user" in lowered or "requires user" in lowered
    if is_blocked and has_blocker and asks_user:
        return "blocked"

    return None


def _block(state_path: Path, state: dict[str, Any]) -> None:
    state["stop_blocks"] = int(state.get("stop_blocks") or 0) + 1
    state["last_blocked_at"] = _now()
    _update_state(state_path, state)
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": BLOCK_REASON,
                "systemMessage": "Active Claude plan implementation goal still needs a Plan Gap Check.",
            },
            separators=(",", ":"),
        )
    )


def main() -> int:
    data = _load_hook_input()
    if data.get("hook_event_name") != "Stop":
        return 0

    state_path = _state_path(data)
    state = _read_state(state_path)
    if state.get("status") != "active":
        return 0

    latest_text = _latest_assistant_text(str(data.get("transcript_path") or state.get("transcript_path") or ""))
    status = _completion_status(latest_text)
    if status in {"complete", "blocked"}:
        state[f"{status}_at"] = _now()
        _update_state(state_path, state, status)
        return 0

    _block(state_path, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
