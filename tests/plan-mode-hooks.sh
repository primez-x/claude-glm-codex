#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

export HOME="$tmp_dir/home"
mkdir -p "$HOME/.claude/plans" "$tmp_dir/repo/docs/superpowers/plans"

transcript="$tmp_dir/session.jsonl"
active_plan="$HOME/.claude/plans/active-plan.md"
cat >"$transcript" <<JSONL
{"type":"attachment","attachment":{"type":"plan_mode","planFilePath":"$active_plan"}}
{"type":"permission-mode","permissionMode":"plan"}
JSONL
not_plan_transcript="$tmp_dir/not-plan-session.jsonl"
cat >"$not_plan_transcript" <<JSONL
{"type":"permission-mode","permissionMode":"default"}
JSONL

run_guard() {
  local payload="$1"
  python3 "$repo_root/hooks/plan-mode-guard.py" <<<"$payload"
}

agent_output="$(
  run_guard "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "PreToolUse",
  "transcript_path": "$transcript",
  "tool_name": "Agent",
  "tool_input": {
    "description": "Explore lane baseline",
    "subagent_type": "general-purpose",
    "model": "opus",
    "run_in_background": True,
    "name": "lane_baseline_scout",
    "prompt": "Read-only exploration for Titan lane evidence planning. Scope: engine/model_lanes/lane_baseline_runner.py and tests. Do not edit. Return concise findings.",
  },
}))
PY
)"
)"

if [[ -z "$agent_output" ]]; then
  printf 'Expected plan-mode Agent tool use to be explicitly allowed, got no hook output.\n' >&2
  exit 1
fi
python3 - "$agent_output" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
specific = data.get("hookSpecificOutput") or {}
if specific.get("permissionDecision") != "allow":
    raise SystemExit("Plan-mode Agent tool use should be explicitly allowed")
updated = specific.get("updatedInput") or {}
if updated.get("subagent_type") != "spark-explorer":
    raise SystemExit(f"Bounded plan-mode scout should route to spark-explorer, got: {updated!r}")
if updated.get("model") != "gpt-5.3-codex-spark":
    raise SystemExit(f"Bounded plan-mode scout should route to gpt-5.3-codex-spark, got: {updated!r}")
if updated.get("name") != "lane_baseline_scout":
    raise SystemExit("Agent routing should preserve the mailbox name")
PY

tiny_agent="$(
  run_guard "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "PreToolUse",
  "transcript_path": "$transcript",
  "tool_name": "Agent",
  "tool_input": {
    "description": "Quick symbol lookup",
    "subagent_type": "general-purpose",
    "model": "opus",
    "run_in_background": True,
    "name": "symbol_scout",
    "prompt": "Tiny quick rg symbol lookup for exact file references. Do not edit.",
  },
}))
PY
)"
)"
python3 - "$tiny_agent" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
specific = data.get("hookSpecificOutput") or {}
updated = specific.get("updatedInput") or {}
if specific.get("permissionDecision") != "allow":
    raise SystemExit("Tiny plan-mode Agent tool use should be explicitly allowed")
if updated.get("subagent_type") != "spark-explorer":
    raise SystemExit(f"Tiny plan-mode lookup should route to spark-explorer, got: {updated!r}")
if updated.get("model") != "gpt-5.3-codex-spark":
    raise SystemExit(f"Tiny plan-mode lookup should route to gpt-5.3-codex-spark, got: {updated!r}")
PY

glm_codex_agent="$(
  CLAUDE_GLM_CODEX_WRAPPER=1 run_guard "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "PreToolUse",
  "transcript_path": "$transcript",
  "tool_name": "Agent",
  "tool_input": {
    "description": "Explore backend evidence service + router",
    "subagent_type": "Explore",
    "model": "opus",
    "run_in_background": True,
    "name": "backend_evidence_scout",
    "prompt": "Read-only exploration for backend evidence service and router. Do not edit.",
  },
}))
PY
)"
)"
python3 - "$glm_codex_agent" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
specific = data.get("hookSpecificOutput") or {}
updated = specific.get("updatedInput") or {}
if specific.get("permissionDecision") != "allow":
    raise SystemExit("GLM-Codex plan-mode Agent tool use should be explicitly allowed")
if updated.get("subagent_type") != "spark-explorer":
    raise SystemExit(f"GLM-Codex bounded scout should route to spark-explorer, got: {updated!r}")
if updated.get("model") != "haiku":
    raise SystemExit(f"GLM-Codex bounded scout must use Agent schema alias haiku, got: {updated!r}")
PY

large_file="$tmp_dir/repo/large_context.py"
python3 - <<PY
from pathlib import Path
Path("$large_file").write_text("x = 'large context fallback'\\n" * 30000, encoding="utf-8")
PY
large_agent="$(
  run_guard "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "PreToolUse",
  "cwd": "$tmp_dir/repo",
  "transcript_path": "$transcript",
  "tool_name": "Agent",
  "tool_input": {
    "description": "Explore large context file",
    "subagent_type": "general-purpose",
    "model": "opus",
    "run_in_background": True,
    "name": "large_context_scout",
    "prompt": "Read-only exploration for $large_file. Do not edit. Return concise findings.",
  },
}))
PY
)"
)"
python3 - "$large_agent" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
specific = data.get("hookSpecificOutput") or {}
updated = specific.get("updatedInput") or {}
if specific.get("permissionDecision") != "allow":
    raise SystemExit("Large-context plan-mode Agent tool use should be explicitly allowed")
if updated.get("subagent_type") != "Explore":
    raise SystemExit(f"Large-context plan-mode scout should route to Explore, got: {updated!r}")
if updated.get("model") != "gpt-5.4-mini":
    raise SystemExit(f"Large-context plan-mode scout should route to gpt-5.4-mini, got: {updated!r}")
PY

glm_codex_large_agent="$(
  CLAUDE_GLM_CODEX_WRAPPER=1 run_guard "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "PreToolUse",
  "cwd": "$tmp_dir/repo",
  "transcript_path": "$transcript",
  "tool_name": "Agent",
  "tool_input": {
    "description": "Explore large context file",
    "subagent_type": "Explore",
    "model": "opus",
    "run_in_background": True,
    "name": "glm_codex_large_context_scout",
    "prompt": "Read-only exploration for $large_file. Do not edit. Return concise findings.",
  },
}))
PY
)"
)"
python3 - "$glm_codex_large_agent" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
specific = data.get("hookSpecificOutput") or {}
updated = specific.get("updatedInput") or {}
if specific.get("permissionDecision") != "allow":
    raise SystemExit("GLM-Codex large-context plan-mode Agent tool use should be explicitly allowed")
if updated.get("subagent_type") != "Explore":
    raise SystemExit(f"GLM-Codex large-context scout should stay on Explore, got: {updated!r}")
if updated.get("model") != "sonnet":
    raise SystemExit(f"GLM-Codex large-context scout must use Agent schema alias sonnet, got: {updated!r}")
PY

readonly_bash="$(
  run_guard "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "PreToolUse",
  "cwd": "$tmp_dir/repo",
  "transcript_path": "$transcript",
  "tool_name": "Bash",
  "tool_input": {
    "command": "rg --files $tmp_dir/repo | rg 'lane|baseline'",
    "description": "Find lane baseline related files",
  },
}))
PY
)"
)"
if [[ -z "$readonly_bash" ]]; then
  printf 'Expected plan-mode read-only Bash to be explicitly allowed, got no hook output.\n' >&2
  exit 1
fi
python3 - "$readonly_bash" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
specific = data.get("hookSpecificOutput") or {}
if specific.get("permissionDecision") != "allow":
    raise SystemExit("Plan-mode read-only Bash should be explicitly allowed")
PY

mutating_bash="$(
  run_guard "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "PreToolUse",
  "cwd": "$tmp_dir/repo",
  "transcript_path": "$transcript",
  "tool_name": "Bash",
  "tool_input": {"command": "touch $tmp_dir/repo/created.txt"},
}))
PY
)"
)"
if [[ -z "$mutating_bash" ]]; then
  printf 'Expected plan-mode mutating Bash to be denied, got no hook output.\n' >&2
  exit 1
fi
python3 - "$mutating_bash" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
specific = data.get("hookSpecificOutput") or {}
if specific.get("permissionDecision") != "deny":
    raise SystemExit("Plan-mode mutating Bash should be denied")
PY

task_output="$(
  run_guard "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "PreToolUse",
  "cwd": "$tmp_dir/repo",
  "transcript_path": "$transcript",
  "tool_name": "TaskOutput",
  "tool_input": {"task_id": "lane_baseline_scout", "block": True},
}))
PY
)"
)"
if [[ -z "$task_output" ]]; then
  printf 'Expected plan-mode TaskOutput by agent name to be denied with guidance, got no hook output.\n' >&2
  exit 1
fi
python3 - "$task_output" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
specific = data.get("hookSpecificOutput") or {}
reason = specific.get("permissionDecisionReason", "")
if specific.get("permissionDecision") != "deny":
    raise SystemExit("Plan-mode TaskOutput with agent names should be denied")
if "TaskOutput" not in reason or "task-notification" not in reason:
    raise SystemExit(f"TaskOutput denial should explain task-notification flow, got: {reason!r}")
PY

agent_mailbox_task_output="$(
  run_guard "$(python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "PreToolUse",
  "cwd": "$tmp_dir/repo",
  "transcript_path": "$not_plan_transcript",
  "tool_name": "TaskOutput",
  "tool_input": {"task_id": "lane-runtime-mapper@session-40c1e434", "block": True},
}))
PY
)"
)"
if [[ -z "$agent_mailbox_task_output" ]]; then
  printf 'Expected TaskOutput by Agent mailbox ID to be denied globally, got no hook output.\n' >&2
  exit 1
fi
python3 - "$agent_mailbox_task_output" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
specific = data.get("hookSpecificOutput") or {}
reason = specific.get("permissionDecisionReason", "")
if specific.get("permissionDecision") != "deny":
    raise SystemExit("TaskOutput with Agent mailbox IDs should be denied globally")
if "Agent mailbox" not in reason or "@session-" not in reason:
    raise SystemExit(f"Global TaskOutput denial should explain Agent mailbox IDs, got: {reason!r}")
PY

repo_plan="$tmp_dir/repo/docs/superpowers/plans/2026-07-04-test-plan.md"
plan_content=$'# Test Implementation Plan\n\n## Goal\n\nBuild a focused test plan.\n\n## Task 1\n\n- [ ] Step 1\n- [ ] Step 2\n'
write_payload="$(
  PLAN_CONTENT="$plan_content" python3 - <<PY
import json
import os
print(json.dumps({
  "hook_event_name": "PreToolUse",
  "cwd": "$tmp_dir/repo",
  "transcript_path": "$transcript",
  "tool_name": "Write",
  "tool_input": {
    "file_path": "$repo_plan",
    "content": os.environ["PLAN_CONTENT"],
  },
}))
PY
)"
write_decision="$(run_guard "$write_payload")"
if [[ -z "$write_decision" ]]; then
  printf 'Expected repo plan document write to be explicitly allowed, got no hook output.\n' >&2
  exit 1
fi
python3 - "$write_decision" <<'PY'
import json
import sys

data = json.loads(sys.argv[1])
specific = data.get("hookSpecificOutput") or {}
if specific.get("permissionDecision") != "allow":
    raise SystemExit("Repo plan document write should be explicitly allowed")
PY

printf '%s' "$plan_content" >"$repo_plan"
mirror_payload="$(
  python3 - <<PY
import json
print(json.dumps({
  "hook_event_name": "PostToolUse",
  "cwd": "$tmp_dir/repo",
  "transcript_path": "$transcript",
  "tool_name": "Write",
  "tool_input": {"file_path": "$repo_plan"},
  "tool_response": {"filePath": "$repo_plan"},
}))
PY
)"
python3 "$repo_root/hooks/plan-file-mirror.py" <<<"$mirror_payload"

PLAN_CONTENT="$plan_content" ACTIVE_PLAN="$active_plan" python3 - <<'PY'
import os
from pathlib import Path

expected = os.environ["PLAN_CONTENT"]
actual = Path(os.environ["ACTIVE_PLAN"]).read_text(encoding="utf-8")
if actual != expected:
    raise SystemExit("Expected active Claude plan file to mirror repo plan content.")
PY

echo "plan-mode hooks contract passed"
