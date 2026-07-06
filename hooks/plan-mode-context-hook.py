#!/usr/bin/env python3
"""Inject plan-mode formatting and agent-result guidance."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PLAN_MODE_CONTEXT = """Plan-mode operating contract:

Agent collection:
- Read-only Agent fanout is allowed for bounded evidence gathering.
- Use Spark first for bounded read-only exploration that fits its 128K text context: tiny file reads, rg/file maps, symbol lookup, log slices, quick summaries, simple checks, and most scoped scout tasks.
- Use `mini-explorer` (GPT-5.4 Mini) when a broad read-only scope should split into multiple Spark scouts, when many files may exceed Spark's context, or when Spark reports a tool-call/schema failure.
- Do not call TaskOutput for Agent mailbox names or agent_id values. Agent results arrive in the parent transcript as <agent-result> or <task-notification> blocks.
- If an agent result has not arrived, continue with available evidence or state the missing input; do not retry TaskOutput by guessing IDs.

Readable plan output:
- Keep final plan synthesis in the parent planning session.
- Do not paste raw scout output into the plan. Condense scout findings into short grouped evidence.
- Use this structure for ExitPlanMode and any repo plan document:
  1. Goal
  2. Current State
  3. Implementation Plan
  4. Verification
  5. Risks And Open Questions
- In Current State, group evidence by topic. Keep bullets to one or two lines, put file:line references at the end, and avoid nested walls of bullets.
- In Implementation Plan, use task-oriented checklist items with concrete files/components and verification for each phase.
"""


def _load_hook_input() -> dict[str, Any]:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_latest_plan_state(transcript_path: Path) -> bool:
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
        return False
    return in_plan_mode


def main() -> int:
    data = _load_hook_input()
    if data.get("hook_event_name") != "UserPromptSubmit":
        return 0

    transcript_raw = data.get("transcript_path")
    if not isinstance(transcript_raw, str) or not transcript_raw:
        return 0

    if not _read_latest_plan_state(Path(transcript_raw).expanduser()):
        return 0

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": PLAN_MODE_CONTEXT,
                }
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
