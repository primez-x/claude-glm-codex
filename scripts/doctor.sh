#!/usr/bin/env bash
set -euo pipefail

BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
LITELLM_CONFIG="${CLAUDE_GATEWAY_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/litellm/claude-glm-codex.yaml}"
CLAUDE_GLM_ENV="${CLAUDE_GLM_CODEX_ENV_FILE:-${CLAUDE_GLM_ENV_FILE:-$HOME/.config/claude-glm/env}}"
AGENTS="${CLAUDE_GLM_CODEX_AGENTS_FILE:-${XDG_CONFIG_HOME:-$HOME/.config}/claude-glm-codex/agents.json}"
RUNTIME="${CLAUDE_GLM_CODEX_SITE_CUSTOMIZE:-$HOME/.local/share/claude-glm-codex/sitecustomize.py}"
PROMPT="${CLAUDE_GLM_CODEX_SYSTEM_PROMPT_FILE:-$HOME/.claude/prompts/fable-provider-native-system-glm-codex.md}"
SUBAGENT_PROMPT="${CLAUDE_GLM_CODEX_SUBAGENT_PROMPT_FILE:-$HOME/.claude/prompts/claude-glm-codex-subagents.md}"

ok() { printf 'OK: %s\n' "$1"; }
warn() { printf 'WARN: %s\n' "$1" >&2; }
fail() { printf 'FAIL: %s\n' "$1" >&2; exit 1; }

check_command() {
  if command -v "$1" >/dev/null 2>&1; then ok "found $1"; else warn "missing $1"; fi
}

check_command claude
check_command litellm
check_command python3
check_command curl
check_command pgrep

[[ -x "$BIN_DIR/claude-glm-codex" ]] && ok "launcher is executable: $BIN_DIR/claude-glm-codex" || warn "launcher missing or not executable: $BIN_DIR/claude-glm-codex"
[[ -x "$BIN_DIR/claude-glm-codex-litellm" ]] && ok "gateway wrapper is executable: $BIN_DIR/claude-glm-codex-litellm" || warn "gateway wrapper missing or not executable: $BIN_DIR/claude-glm-codex-litellm"
[[ -f "$CLAUDE_GLM_ENV" ]] && ok "private GLM env exists: $CLAUDE_GLM_ENV" || warn "private GLM env missing: $CLAUDE_GLM_ENV"
[[ -f "$LITELLM_CONFIG" ]] && ok "LiteLLM config exists: $LITELLM_CONFIG" || fail "LiteLLM config missing: $LITELLM_CONFIG"
[[ -f "$AGENTS" ]] && ok "agents file exists: $AGENTS" || fail "agents file missing: $AGENTS"
[[ -f "$RUNTIME" ]] && ok "gateway shim exists: $RUNTIME" || fail "gateway shim missing: $RUNTIME"
[[ -f "$PROMPT" ]] && ok "system prompt exists: $PROMPT" || fail "system prompt missing: $PROMPT"
[[ -f "$SUBAGENT_PROMPT" ]] && ok "subagent prompt exists: $SUBAGENT_PROMPT" || fail "subagent prompt missing: $SUBAGENT_PROMPT"

HOOK_PATH="$RUNTIME" python3 -B <<'PY'
import os
from pathlib import Path
path = Path(os.environ["HOOK_PATH"])
compile(path.read_text(), str(path), "exec")
PY
ok "gateway shim syntax is valid"

CONFIG="$LITELLM_CONFIG" AGENTS="$AGENTS" python3 <<'PY'
import json
import os
from pathlib import Path
try:
    import yaml
except Exception as exc:
    raise SystemExit(f"FAIL: PyYAML unavailable: {exc}")

config = yaml.safe_load(Path(os.environ["CONFIG"]).read_text())
names = [item.get("model_name") for item in config.get("model_list", []) if isinstance(item, dict)]
required = {
    "glm-codex-hybrid",
    "opus",
    "claude-opus-4-7",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex-spark",
    "claude-sonnet-4-6",
    "sonnet",
    "haiku",
}
missing = sorted(required.difference(names))
if missing:
    raise SystemExit(f"FAIL: LiteLLM config missing routes: {', '.join(missing)}")
agents = json.loads(Path(os.environ["AGENTS"]).read_text())
required_agents = {"spark-explorer", "mini-explorer", "spark-formatter", "spark-checker", "spark-summarizer", "codex-worker", "codex-reviewer", "codex-verifier"}
missing_agents = sorted(required_agents.difference(agents))
if missing_agents:
    raise SystemExit(f"FAIL: agents file missing agents: {', '.join(missing_agents)}")
print(f"OK: parsed {len(names)} model routes and {len(agents)} agents")
PY

printf '\nDoctor checks finished.\n'
