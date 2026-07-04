#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

module_dir="$tmp_dir/litellm/completion_extras/litellm_responses_transformation"
mkdir -p "$module_dir"
touch "$tmp_dir/litellm/__init__.py"
mkdir -p "$tmp_dir/litellm/completion_extras"
touch "$tmp_dir/litellm/completion_extras/__init__.py"
touch "$module_dir/__init__.py"
cat >"$module_dir/transformation.py" <<'PY'
class LiteLLMResponsesTransformationHandler:
    def convert_chat_completion_messages_to_responses_api(self, messages):
        for message in messages:
            if isinstance(message, dict) and message.get("role") in {"system", "developer"}:
                raise AssertionError("system/developer message reached original converter")
        return messages, "existing instructions"
PY

PYTHONPATH="$repo_root/config/python:$tmp_dir" python3 <<'PY'
from litellm.completion_extras.litellm_responses_transformation.transformation import (
    LiteLLMResponsesTransformationHandler,
)

handler = LiteLLMResponsesTransformationHandler()
input_items, instructions = handler.convert_chat_completion_messages_to_responses_api(
    [
        {"role": "system", "content": "base system"},
        {"role": "developer", "content": [{"type": "text", "text": "developer hint"}]},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": {"text": "hi"}},
    ]
)

assert input_items == [
    {"role": "user", "content": "hello"},
    {"role": "assistant", "content": {"text": "hi"}},
]
assert instructions == "base system\n\ndeveloper hint\n\nexisting instructions"
print("system-message shim contract passed")
PY
