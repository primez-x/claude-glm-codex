#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

bash -n bin/claude-glm-codex
bash -n bin/claude-glm-codex-litellm
bash -n scripts/install.sh
bash -n scripts/doctor.sh
bash -n scripts/verify-release.sh
bash -n tests/launcher-contract.sh
bash -n tests/system-message-shim.sh
bash -n tests/plan-gap-hook.sh
bash -n tests/plan-mode-hooks.sh
bash -n tests/plan-mode-context-hook.sh

tests/launcher-contract.sh
tests/system-message-shim.sh
tests/plan-gap-hook.sh
tests/plan-mode-hooks.sh
tests/plan-mode-context-hook.sh

python3 -B <<'PY'
from pathlib import Path
for path in (
    Path("config/python/sitecustomize.py"),
    Path("hooks/plan-mode-guard.py"),
    Path("hooks/plan-file-mirror.py"),
    Path("hooks/plan-gap-goal-hook.py"),
    Path("hooks/plan-gap-stop-hook.py"),
    Path("hooks/plan-mode-context-hook.py"),
):
    compile(path.read_text(), str(path), "exec")
print("Python hooks and gateway shim syntax parsed")
PY

python3 <<'PY'
import json
from pathlib import Path
json.loads(Path("config/claude/agents.json").read_text())
json.loads(Path("config/claude/settings.hooks.example.json").read_text())
print("JSON config parsed")
PY

python3 <<'PY'
from pathlib import Path
try:
    import yaml
except Exception as exc:
    raise SystemExit(f"PyYAML is required for release verification: {exc}")
data = yaml.safe_load(Path("config/litellm/claude-glm-codex.yaml").read_text())
names = [item.get("model_name") for item in data.get("model_list", []) if isinstance(item, dict)]
required = {"glm-codex-hybrid", "fable", "opus", "glm-5.2", "gpt-5.5", "gpt-5.3-codex-spark", "sonnet", "haiku"}
missing = sorted(required.difference(names))
if missing:
    raise SystemExit(f"LiteLLM YAML missing required routes: {', '.join(missing)}")
print(f"LiteLLM YAML parsed with {len(names)} routes")
PY

python3 <<'PY'
from pathlib import Path
prompt = Path("prompts/fable-provider-native-system-glm-codex.md").read_text()
required = [
    "AskUserQuestion safety",
    "Do not use AskUserQuestion for implementation scope choices",
    "If AskUserQuestion is truly necessary, ask exactly one question",
]
missing = [item for item in required if item not in prompt]
if missing:
    raise SystemExit(f"Prompt missing AskUserQuestion guard text: {missing!r}")
print("AskUserQuestion prompt guard present")
PY

if rg --pcre2 -n \
  '(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|gho_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----)' \
  --glob '!*.bak' \
  --glob '!.git/**' \
  .; then
  printf 'Potential secret-like value found. Review output above.\n' >&2
  exit 1
fi

if find . -path ./.git -prune -o \( -name '.env' -o -name '*.pem' -o -name '*.key' -o -name 'auth.json' -o -name '*.jsonl' \) -print | rg .; then
  printf 'Sensitive runtime file pattern found in working tree.\n' >&2
  exit 1
fi

if rg -n 'ANTHROPIC_AUTH_TOKEN=.*[A-Za-z0-9_./+-]{20,}|ANTHROPIC_BASE_URL=https?://[^"$\{]' --glob '!*README.md' --glob '!.git/**' .; then
  printf 'Literal provider env values found; use variable names/placeholders only.\n' >&2
  exit 1
fi

git diff --check
printf 'Release verification passed.\n'
