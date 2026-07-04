#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
hook="$repo_root/hooks/plan-gap-goal-hook.py"
stop_hook="$repo_root/hooks/plan-gap-stop-hook.py"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

export HOME="$tmp_dir/home"
mkdir -p "$HOME"

run_hook() {
  local payload="$1"
  python3 "$hook" <<<"$payload"
}

run_stop_hook() {
  local payload="$1"
  python3 "$stop_hook" <<<"$payload"
}

normal_output="$(run_hook '{"hook_event_name":"UserPromptSubmit","prompt":"hello","session_id":"s1"}')"
if [[ -n "$normal_output" ]]; then
  printf 'Expected no output for non-trigger prompt, got: %s\n' "$normal_output" >&2
  exit 1
fi

wrong_event_output="$(run_hook '{"hook_event_name":"Stop","prompt":"Implement the plan.","session_id":"s1"}')"
if [[ -n "$wrong_event_output" ]]; then
  printf 'Expected no output for wrong hook event, got: %s\n' "$wrong_event_output" >&2
  exit 1
fi

transcript="$tmp_dir/session.jsonl"
trigger_output="$(run_hook "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "UserPromptSubmit",
  "prompt": "Implement the plan.",
  "session_id": "s1",
  "transcript_path": "$transcript",
  "cwd": "$tmp_dir/repo",
}))
PY
)")"

python3 - "$trigger_output" <<'PY'
import json
import sys

raw = sys.argv[1]
try:
    data = json.loads(raw)
except Exception as exc:
    raise SystemExit(f"Hook output must be JSON, got {raw!r}: {exc}")

specific = data.get("hookSpecificOutput")
if not isinstance(specific, dict):
    raise SystemExit("Hook output missing hookSpecificOutput")
if specific.get("hookEventName") != "UserPromptSubmit":
    raise SystemExit("Hook output must target UserPromptSubmit")

context = specific.get("additionalContext")
if not isinstance(context, str) or not context.strip():
    raise SystemExit("Hook output missing additionalContext")

required_fragments = [
    "Active Claude plan implementation goal",
    "Implement the accepted plan fully",
    "Conduct a plan implementation gap analysis",
    "Recover the original plan",
    "Compare each commitment against the actual diff",
    "Fix any clear, in-scope missing",
    "Run focused verification",
    "Plan Gap Check",
]
missing = [fragment for fragment in required_fragments if fragment not in context]
if missing:
    raise SystemExit(f"additionalContext missing required fragments: {missing!r}")

if "thread/goal/set" in context or "codex app-server" in context.lower():
    raise SystemExit("Claude hook context should not mention Codex goal transport")

print("plan gap hook contract passed")
PY

state_file="$HOME/.claude/goals/s1.json"
if [[ ! -f "$state_file" ]]; then
  printf 'Expected trigger prompt to persist an active Claude goal at %s.\n' "$state_file" >&2
  exit 1
fi

python3 - "$state_file" <<'PY'
import json
import sys
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text())
if state.get("status") != "active":
    raise SystemExit(f"Expected active goal state, got: {state!r}")
if state.get("session_id") != "s1":
    raise SystemExit(f"Goal state should be session scoped, got: {state!r}")
if "Implement the accepted plan fully" not in state.get("objective", ""):
    raise SystemExit("Goal state missing objective text")
PY

variant_output="$(run_hook '{"hook_event_name":"UserPromptSubmit","prompt":"Implement this plan.","session_id":"s2"}')"
if [[ -z "$variant_output" || ! -f "$HOME/.claude/goals/s2.json" ]]; then
  printf 'Expected Implement this plan. variant to create a persisted goal.\n' >&2
  exit 1
fi

active_context="$(run_hook '{"hook_event_name":"UserPromptSubmit","prompt":"continue","session_id":"s1"}')"
python3 - "$active_context" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
context = (data.get("hookSpecificOutput") or {}).get("additionalContext", "")
if "Active Claude plan implementation goal" not in context:
    raise SystemExit("Expected active goal context on later prompts in the same session")
PY

cat >"$transcript" <<'JSONL'
{"message":{"role":"assistant","content":[{"type":"text","text":"Implemented the requested change."}]}}
JSONL

blocked_output="$(run_stop_hook "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "Stop",
  "session_id": "s1",
  "transcript_path": "$transcript",
}))
PY
)")"
python3 - "$blocked_output" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
if data.get("decision") != "block":
    raise SystemExit(f"Expected Stop hook to block incomplete active goal, got: {data!r}")
reason = data.get("reason", "")
if "Plan Gap Check" not in reason or "Verification" not in reason:
    raise SystemExit(f"Stop hook block reason should ask for the missing goal evidence, got: {reason!r}")
PY

cat >"$transcript" <<'JSONL'
{"message":{"role":"assistant","content":[{"type":"text","text":"Plan Gap Check\nPlan recovered: implemented the accepted plan.\nGap checklist: compared committed plan items against the diff.\nFixes applied: no remaining in-scope gaps.\nVerification: focused hook tests passed.\nRemaining risk: none known."}]}}
JSONL

complete_output="$(run_stop_hook "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "Stop",
  "session_id": "s1",
  "transcript_path": "$transcript",
}))
PY
)")"
if [[ -n "$complete_output" ]]; then
  printf 'Expected complete goal Stop hook to allow stop silently, got: %s\n' "$complete_output" >&2
  exit 1
fi
python3 - "$state_file" <<'PY'
import json
import sys
from pathlib import Path

state = json.loads(Path(sys.argv[1]).read_text())
if state.get("status") != "complete":
    raise SystemExit(f"Expected Stop hook to mark goal complete, got: {state!r}")
PY
