#!/usr/bin/env python3
"""Persist and inject a plan-implementation gap-analysis goal."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TRIGGER_PROMPTS = {
    "implement the plan",
    "implement this plan",
    "yes, implement this plan",
}
CANCEL_PROMPTS = {
    "cancel plan goal",
    "clear plan goal",
    "clear claude plan goal",
}

OBJECTIVE = """Plan implementation objective:

Implement the accepted plan fully. Treat the accepted plan as the contract for the work.

After the implementation appears complete, do not stop. Conduct a plan implementation gap analysis before giving the final answer:
- Recover the original plan and turn it into a checklist of concrete commitments.
- Compare each commitment against the actual diff, relevant code paths, tests, docs, config, and generated artifacts.
- Fix any clear, in-scope missing, partial, contradicted, or buggy implementation pieces.
- Run focused verification after the fixes.
- Only finish after reporting the plan recovered, gap checklist, fixes applied, verification, and remaining risk.

Completion means both the implementation and the gap analysis loop are complete.

Final answer requirement:
Include a concise Plan Gap Check with these labels before stopping:
- Plan recovered
- Gap checklist
- Fixes applied
- Verification
- Remaining risk"""


def _load_hook_input() -> dict[str, Any]:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_prompt(prompt: str) -> str:
    normalized = re.sub(r"\s+", " ", prompt.strip()).casefold()
    return normalized.rstrip(".!?")


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


def _set_goal(data: dict[str, Any], prompt: str) -> dict[str, Any]:
    path = _state_path(data)
    existing = _read_state(path)
    _, session_id = _state_identity(data)
    now = _now()
    state = {
        "schema_version": 1,
        "status": "active",
        "session_id": session_id,
        "transcript_path": str(data.get("transcript_path") or ""),
        "cwd": str(data.get("cwd") or ""),
        "trigger_prompt": prompt,
        "objective": OBJECTIVE,
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
        "stop_blocks": int(existing.get("stop_blocks") or 0),
    }
    _write_state(path, state)
    return state


def _update_status(data: dict[str, Any], status: str) -> None:
    path = _state_path(data)
    state = _read_state(path)
    if not state:
        return
    state["status"] = status
    state["updated_at"] = _now()
    _write_state(path, state)


def _active_state(data: dict[str, Any]) -> dict[str, Any]:
    state = _read_state(_state_path(data))
    return state if state.get("status") == "active" else {}


def _context_for_goal(state: dict[str, Any]) -> str:
    created = state.get("created_at") or "unknown"
    transcript = state.get("transcript_path") or "unknown transcript"
    return f"""Active Claude plan implementation goal:
- Status: active
- Created: {created}
- Transcript: {transcript}

{OBJECTIVE}

The Stop hook enforces this goal for the current session. If the work is genuinely blocked, report a clear Goal blocked section with the blocking condition and what is needed from the user."""


def _print_context(context: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            },
            separators=(",", ":"),
        )
    )


def main() -> int:
    data = _load_hook_input()
    if data.get("hook_event_name") != "UserPromptSubmit":
        return 0

    prompt = str(data.get("prompt") or "")
    normalized = _normalize_prompt(prompt)

    if normalized in CANCEL_PROMPTS:
        _update_status(data, "cancelled")
        return 0

    if normalized in TRIGGER_PROMPTS:
        state = _set_goal(data, prompt)
        _print_context(_context_for_goal(state))
        return 0

    state = _active_state(data)
    if not state:
        return 0

    _print_context(_context_for_goal(state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
