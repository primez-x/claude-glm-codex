#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

export HOME="$tmp_dir/home"
export CAPTURE_FILE="$tmp_dir/capture.json"
mkdir -p "$HOME/.local/bin" "$HOME/.config/claude-glm" "$HOME/.config/claude-glm-codex" "$HOME/.config/litellm" "$HOME/.claude/prompts"
cp "$repo_root/config/claude/agents.json" "$HOME/.config/claude-glm-codex/agents.json"
cp "$repo_root/config/litellm/claude-glm-codex.yaml" "$HOME/.config/litellm/claude-glm-codex.yaml"
cp "$repo_root/prompts/fable-provider-native-system-glm-codex.md" "$HOME/.claude/prompts/fable-provider-native-system-glm-codex.md"
cp "$repo_root/prompts/claude-glm-codex-subagents.md" "$HOME/.claude/prompts/claude-glm-codex-subagents.md"

cat >"$HOME/.config/claude-glm/env" <<'ENV'
ANTHROPIC_AUTH_TOKEN="dummy"
ANTHROPIC_BASE_URL="https://glm.example.invalid"
ANTHROPIC_DEFAULT_OPUS_MODEL="glm-5.2[1m]"
ENV
chmod 0600 "$HOME/.config/claude-glm/env"

cat >"$HOME/.local/bin/claude-glm-codex-litellm" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
python3 - "$CAPTURE_FILE" "$@" <<'PY'
import json
import os
import sys
keys = [
    "CLAUDE_GATEWAY_CONFIG",
    "CLAUDE_GATEWAY_MODEL",
    "CLAUDE_GATEWAY_SMALL_FAST_MODEL",
    "CLAUDE_GLM_UPSTREAM_AUTH_TOKEN",
    "CLAUDE_GLM_UPSTREAM_BASE_URL",
    "CLAUDE_GLM_UPSTREAM_OPUS_MODEL",
    "CLAUDE_CODE_ENABLE_EXPERIMENTAL_ADVISOR_TOOL",
    "CLAUDE_CODE_DISABLE_ADVISOR_TOOL",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_BG_CLASSIFIER_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_GLM_CODEX_WRAPPER",
]
with open(sys.argv[1], "w", encoding="utf-8") as fh:
    json.dump({"args": sys.argv[2:], "env": {key: os.environ.get(key) for key in keys}}, fh, sort_keys=True)
PY
SH
chmod +x "$HOME/.local/bin/claude-glm-codex-litellm"

CLAUDE_GLM_CODEX_NO_TMUX=1 "$repo_root/bin/claude-glm-codex" --no-tmux --effort max probe

python3 - "$CAPTURE_FILE" "$HOME" <<'PY'
import json
import sys
from pathlib import Path
data = json.loads(Path(sys.argv[1]).read_text())
home = Path(sys.argv[2])
args = data["args"]
env = data["env"]

def require(condition, message):
    if not condition:
        raise SystemExit(message)

require("--no-tmux" not in args, "--no-tmux leaked to downstream wrapper")
require("--system-prompt-file" in args, "system prompt file was not injected")
require(args[args.index("--system-prompt-file") + 1] == str(home / ".claude/prompts/fable-provider-native-system-glm-codex.md"), "wrong system prompt path")
require("--append-system-prompt" in args, "subagent prompt was not appended")
require("--agents" in args and any('"spark-explorer"' in arg for arg in args), "agents JSON was not injected")
require("--dangerously-skip-permissions" in args, "GLM-Codex launcher should preserve permissive local workflow default")
require("--model" in args and args[args.index("--model") + 1] == "opus", "default model should be opus")
require("--effort" in args and args[args.index("--effort") + 1] == "xhigh", "max effort should normalize to xhigh")
require(args[-1] == "probe", "user argument not preserved")

expected = {
    "CLAUDE_GATEWAY_CONFIG": str(home / ".config/litellm/claude-glm-codex.yaml"),
    "CLAUDE_GATEWAY_MODEL": "opus",
    "CLAUDE_GATEWAY_SMALL_FAST_MODEL": "gpt-5.3-codex-spark",
    "CLAUDE_GLM_UPSTREAM_AUTH_TOKEN": "dummy",
    "CLAUDE_GLM_UPSTREAM_BASE_URL": "https://glm.example.invalid",
    "CLAUDE_GLM_UPSTREAM_OPUS_MODEL": "anthropic/glm-5.2",
    "CLAUDE_CODE_ENABLE_EXPERIMENTAL_ADVISOR_TOOL": "1",
    "CLAUDE_CODE_DISABLE_ADVISOR_TOOL": "0",
    "CLAUDE_CODE_SUBAGENT_MODEL": "inherit",
    "CLAUDE_CODE_BG_CLASSIFIER_MODEL": "haiku",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "glm-5.2[1m]",
    "ANTHROPIC_DEFAULT_FABLE_MODEL": "glm-codex-hybrid",
    "ANTHROPIC_DEFAULT_FABLE_MODEL_NAME": "GLM-Codex Smart Advisor",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "gpt-5.5",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "gpt-5.3-codex-spark",
    "CLAUDE_GLM_CODEX_WRAPPER": "1",
}
for key, value in expected.items():
    require(env.get(key) == value, f"{key} expected {value!r}, got {env.get(key)!r}")
print("glm-codex launcher contract passed")
PY
