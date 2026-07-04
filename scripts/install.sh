#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${PREFIX:-$HOME/.local}"
BIN_DIR="${BIN_DIR:-$PREFIX/bin}"
LITELLM_CONFIG_DIR="${LITELLM_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/litellm}"
CLAUDE_DIR="${CLAUDE_DIR:-$HOME/.claude}"
CLAUDE_GLM_CODEX_CONFIG_DIR="${CLAUDE_GLM_CODEX_CONFIG_DIR:-${XDG_CONFIG_HOME:-$HOME/.config}/claude-glm-codex}"
CLAUDE_GLM_CODEX_RUNTIME_DIR="${CLAUDE_GLM_CODEX_RUNTIME_DIR:-$PREFIX/share/claude-glm-codex}"
FORCE=0
DRY_RUN=0
INSTALL_HOOK=1

usage() {
  cat <<'EOF'
Usage: scripts/install.sh [options]

Options:
  --force          Overwrite existing launcher/config files.
  --dry-run        Print actions without changing files.
  --no-hook        Do not install or register Claude hooks.
  -h, --help       Show this help.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --force) FORCE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --no-hook) INSTALL_HOOK=0 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

run() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf 'DRY RUN:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

install_file() {
  local src="$1"
  local dest="$2"
  local mode="$3"
  if [[ -e "$dest" && "$FORCE" != "1" ]]; then
    printf 'Keeping existing %s. Use --force to overwrite.\n' "$dest"
    return 0
  fi
  run install -D -m "$mode" "$src" "$dest"
}

install_file "$REPO_ROOT/bin/claude-glm-codex" "$BIN_DIR/claude-glm-codex" 0755
install_file "$REPO_ROOT/bin/claude-glm-codex-litellm" "$BIN_DIR/claude-glm-codex-litellm" 0755
install_file "$REPO_ROOT/config/litellm/claude-glm-codex.yaml" "$LITELLM_CONFIG_DIR/claude-glm-codex.yaml" 0644
install_file "$REPO_ROOT/config/claude/agents.json" "$CLAUDE_GLM_CODEX_CONFIG_DIR/agents.json" 0644
install_file "$REPO_ROOT/config/python/sitecustomize.py" "$CLAUDE_GLM_CODEX_RUNTIME_DIR/sitecustomize.py" 0644
install_file "$REPO_ROOT/prompts/fable-provider-native-system-glm-codex.md" "$CLAUDE_DIR/prompts/fable-provider-native-system-glm-codex.md" 0644
install_file "$REPO_ROOT/prompts/claude-glm-codex-subagents.md" "$CLAUDE_DIR/prompts/claude-glm-codex-subagents.md" 0644

if [[ "$INSTALL_HOOK" == "1" ]]; then
  guard_hook_path="$CLAUDE_DIR/hooks/plan-mode-guard.py"
  mirror_hook_path="$CLAUDE_DIR/hooks/plan-file-mirror.py"
  gap_hook_path="$CLAUDE_DIR/hooks/plan-gap-goal-hook.py"
  gap_stop_hook_path="$CLAUDE_DIR/hooks/plan-gap-stop-hook.py"
  context_hook_path="$CLAUDE_DIR/hooks/plan-mode-context-hook.py"
  settings_path="$CLAUDE_DIR/settings.json"
  install_file "$REPO_ROOT/hooks/plan-mode-guard.py" "$guard_hook_path" 0755
  install_file "$REPO_ROOT/hooks/plan-file-mirror.py" "$mirror_hook_path" 0755
  install_file "$REPO_ROOT/hooks/plan-gap-goal-hook.py" "$gap_hook_path" 0755
  install_file "$REPO_ROOT/hooks/plan-gap-stop-hook.py" "$gap_stop_hook_path" 0755
  install_file "$REPO_ROOT/hooks/plan-mode-context-hook.py" "$context_hook_path" 0755

  if [[ "$DRY_RUN" == "1" ]]; then
    printf 'DRY RUN: register Claude hooks in %s\n' "$settings_path"
  else
    CLAUDE_SETTINGS_PATH="$settings_path" \
      CLAUDE_GUARD_HOOK_PATH="$guard_hook_path" \
      CLAUDE_MIRROR_HOOK_PATH="$mirror_hook_path" \
      CLAUDE_GAP_HOOK_PATH="$gap_hook_path" \
      CLAUDE_GAP_STOP_HOOK_PATH="$gap_stop_hook_path" \
      CLAUDE_CONTEXT_HOOK_PATH="$context_hook_path" \
      python3 <<'PY'
import json
import os
import shutil
import time
from pathlib import Path

settings_path = Path(os.environ["CLAUDE_SETTINGS_PATH"]).expanduser()
paths = {
    "guard": str(Path(os.environ["CLAUDE_GUARD_HOOK_PATH"]).expanduser()),
    "mirror": str(Path(os.environ["CLAUDE_MIRROR_HOOK_PATH"]).expanduser()),
    "gap": str(Path(os.environ["CLAUDE_GAP_HOOK_PATH"]).expanduser()),
    "gap_stop": str(Path(os.environ["CLAUDE_GAP_STOP_HOOK_PATH"]).expanduser()),
    "context": str(Path(os.environ["CLAUDE_CONTEXT_HOOK_PATH"]).expanduser()),
}
settings_path.parent.mkdir(parents=True, exist_ok=True)
if settings_path.exists():
    shutil.copy2(settings_path, settings_path.with_suffix(settings_path.suffix + f".bak.{int(time.time())}"))
    data = json.loads(settings_path.read_text())
else:
    data = {}
if not isinstance(data, dict):
    raise SystemExit(f"{settings_path} must contain a JSON object")
hooks_config = data.setdefault("hooks", {})
if not isinstance(hooks_config, dict):
    raise SystemExit(f"{settings_path}: hooks must be a JSON object")

def has_hook(item, command):
    return isinstance(item, dict) and any(
        isinstance(hook, dict) and hook.get("command") == command
        for hook in item.get("hooks", [])
    )

def ensure_hook(event_name, command, *, matcher=None, timeout=None, status_message=None):
    event_hooks = hooks_config.setdefault(event_name, [])
    if not isinstance(event_hooks, list):
        raise SystemExit(f"{settings_path}: hooks.{event_name} must be a JSON array")
    if any(has_hook(item, command) for item in event_hooks):
        return
    hook = {"type": "command", "command": command}
    if timeout is not None:
        hook["timeout"] = timeout
    if status_message:
        hook["statusMessage"] = status_message
    entry = {"hooks": [hook]}
    if matcher is not None:
        entry["matcher"] = matcher
    event_hooks.insert(0, entry)

ensure_hook("PreToolUse", paths["guard"], matcher="")
ensure_hook("PostToolUse", paths["mirror"], matcher="Write")
ensure_hook("UserPromptSubmit", paths["gap"], timeout=5, status_message="Checking plan gap objective")
ensure_hook("Stop", paths["gap_stop"], timeout=10, status_message="Checking plan gap goal")
ensure_hook("UserPromptSubmit", paths["context"], timeout=5, status_message="Loading plan mode contract")
settings_path.write_text(json.dumps(data, indent=2) + "\n")
settings_path.chmod(0o600)
PY
  fi
fi

printf '\nInstalled claude-glm-codex files.\n'
printf 'Private GLM provider values stay in ~/.config/claude-glm/env and are not installed by this repo.\n'
