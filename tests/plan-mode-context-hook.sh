#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

export HOME="$tmp_dir/home"
mkdir -p "$HOME/.claude/plans"

transcript="$tmp_dir/session.jsonl"
active_plan="$HOME/.claude/plans/active-plan.md"
cat >"$transcript" <<JSONL
{"type":"attachment","attachment":{"type":"plan_mode","planFilePath":"$active_plan"}}
{"type":"permission-mode","permissionMode":"plan"}
JSONL

plan_context="$(
  python3 "$repo_root/hooks/plan-mode-context-hook.py" <<JSON
{"hook_event_name":"UserPromptSubmit","transcript_path":"$transcript","prompt":"make a plan"}
JSON
)"

if [[ -z "$plan_context" ]]; then
  printf 'Expected plan-mode context hook to inject additional context.\n' >&2
  exit 1
fi

python3 - "$plan_context" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
specific = data.get("hookSpecificOutput") or {}
context = specific.get("additionalContext", "")
if specific.get("hookEventName") != "UserPromptSubmit":
    raise SystemExit("Wrong hook event name")
required = [
    "Do not call TaskOutput",
    "task-notification",
    "Readable plan output",
    "Do not paste raw scout output",
]
missing = [item for item in required if item not in context]
if missing:
    raise SystemExit(f"Plan-mode context missing required text: {missing!r}")
PY

not_plan="$(
  python3 "$repo_root/hooks/plan-mode-context-hook.py" <<JSON
{"hook_event_name":"UserPromptSubmit","transcript_path":"$tmp_dir/not-plan.jsonl","prompt":"normal prompt"}
JSON
)"
if [[ -n "$not_plan" ]]; then
  printf 'Expected non-plan context hook to stay silent, got: %s\n' "$not_plan" >&2
  exit 1
fi

echo "plan-mode context hook contract passed"
