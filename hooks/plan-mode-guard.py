#!/usr/bin/env python3
"""Fail closed on mutations while Claude Code is in plan mode."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


MUTATING_FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
REQUIRED_TOOL_ARGS = {
    "Bash": ("command",),
    "Glob": ("pattern",),
    "Grep": ("pattern",),
    "Read": ("file_path",),
}
MUTATING_BASH_PATTERNS = (
    r"\bapply_patch\b",
    r"\b(?:chmod|chown|cp|install|ln|mkdir|mv|rm|rmdir|touch)\b",
    r"\b(?:docker|podman)(?:\s+compose)?\s+(?:build|down|kill|restart|rm|run|start|stop|up)\b",
    r"\bgit\s+(?:add|am|apply|checkout|cherry-pick|clean|commit|merge|mv|pull|push|rebase|reset|restore|revert|rm|stash|switch|tag)\b",
    r"\b(?:kill|killall|pkill)\b",
    r"\b(?:npm|pnpm|yarn|bun)\s+(?:add|build|ci|exec|i|install|lint|run|start|test|typecheck|verify)\b",
    r"\b(?:pip|pip3|uv\s+pip)\s+install\b",
    r"\bpytest\b",
    r"\b(?:service|systemctl)\s+(?:disable|enable|reload|restart|start|stop)\b",
    r"\bsed\s+-i\b",
    r"\btee\b",
    r"\b(?:curl|wget)\b[^\n]*(?:\s-[^\s]*[oO]|--output|--remote-name)\b",
    r"\bcurl\b[^\n]*(?:-X|--request)\s*(?:DELETE|PATCH|POST|PUT)\b",
    r"\b(?:vim|nvim|nano|emacs|code)\b",
)
MUTATING_SCRIPT_PATTERNS = (
    r"\.mkdir\s*\(",
    r"\.rename\s*\(",
    r"\.rmdir\s*\(",
    r"\.unlink\s*\(",
    r"\.write_(?:bytes|text)\s*\(",
    r"\bopen\s*\([^,\n]+,\s*[\"'][^\"']*[awx+]",
    r"\bos\.(?:makedirs|mkdir|remove|rename|replace|rmdir|unlink)\s*\(",
    r"\bshutil\.(?:copy|copy2|copyfile|copytree|move|rmtree)\s*\(",
)
OUTPUT_REDIRECT_RE = re.compile(r"(^|[\s;])(?:&>|(?:\d+)?>>?)(?!&|\s*/dev/null\b)")
SPARK_CONTEXT_MAX_BYTES = int(os.environ.get("CLAUDE_CODEX_SPARK_CONTEXT_MAX_BYTES", "524288"))
PATH_TOKEN_RE = re.compile(
    r"(?:~|\.{1,2}|/|[A-Za-z0-9_-])[\w./*-]*"
    r"(?:\.(?:cfg|css|go|h|hpp|html|java|js|json|jsx|md|py|rs|sh|sql|toml|ts|tsx|txt|yaml|yml)|/\*)"
)


def _is_glm_codex_session() -> bool:
    if os.environ.get("CLAUDE_GLM_CODEX_WRAPPER") == "1":
        return True
    config = os.environ.get("CLAUDE_GATEWAY_CONFIG", "")
    return "claude-glm-codex" in config


def _spark_agent_model() -> str:
    explicit = (
        os.environ.get("CLAUDE_CODEX_SPARK_AGENT_MODEL")
        or os.environ.get("CLAUDE_GLM_CODEX_SPARK_AGENT_MODEL")
    )
    if explicit:
        return explicit
    return "haiku" if _is_glm_codex_session() else "gpt-5.3-codex-spark"


def _explore_agent_model() -> str:
    explicit = (
        os.environ.get("CLAUDE_CODEX_EXPLORE_AGENT_MODEL")
        or os.environ.get("CLAUDE_GLM_CODEX_EXPLORE_AGENT_MODEL")
    )
    if explicit:
        return explicit
    return "sonnet" if _is_glm_codex_session() else "gpt-5.4-mini"


def _mini_explorer_agent_type() -> str:
    return os.environ.get("CLAUDE_GLM_CODEX_MINI_EXPLORER_AGENT", "mini-explorer")


SPARK_AGENT_TYPES = {
    "spark-explorer",
    "spark-formatter",
    "spark-checker",
    "spark-summarizer",
}
SONNET_AGENT_TYPES = {
    "codex-worker",
    "codex-reviewer",
    "codex-verifier",
}


def _load_hook_input() -> dict[str, Any]:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _deny(reason: str, additional_context: str | None = None) -> int:
    context = additional_context
    if context is None:
        context = (
            "You are in a protected planning/read-only context. Present the "
            "plan with ExitPlanMode from the parent planning session and wait "
            "for explicit user approval before editing files, running "
            "verification, committing, or mutating runtime state. Read-only "
            "exploration commands are allowed."
        )
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
            "additionalContext": context,
        }
    }
    print(json.dumps(payload))
    return 0


def _allow(
    reason: str,
    additional_context: str | None = None,
    updated_input: dict[str, Any] | None = None,
) -> int:
    output: dict[str, Any] = {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": reason,
    }
    if additional_context:
        output["additionalContext"] = additional_context
    if updated_input is not None:
        output["updatedInput"] = updated_input
    print(json.dumps({"hookSpecificOutput": output}, separators=(",", ":")))
    return 0


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except Exception:
        return False


def _read_latest_plan_state(transcript_path: Path) -> tuple[Path | None, bool]:
    plan_path: Path | None = None
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
                        raw_plan_path = attachment.get("planFilePath")
                        if isinstance(raw_plan_path, str) and raw_plan_path:
                            plan_path = Path(raw_plan_path).expanduser()
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
        return None, False

    return plan_path, in_plan_mode


def _message_text(message: Any) -> str:
    if isinstance(message, str):
        return message
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, dict) and isinstance(item.get("content"), str):
                parts.append(item["content"])
        return "\n".join(parts)
    return ""


def _transcript_is_read_only_sidechain(transcript_path: Path) -> bool:
    try:
        with transcript_path.open("r", encoding="utf-8") as transcript:
            for index, line in enumerate(transcript):
                if index >= 40:
                    break
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                if not event.get("isSidechain"):
                    continue
                if event.get("type") != "user":
                    continue

                text = _message_text(event.get("message")).lower()
                if not text:
                    continue
                read_only_signals = (
                    "read-only",
                    "do not edit",
                    "do not modify",
                    "do not commit",
                    "do not restart",
                    "no code changes",
                )
                if any(signal in text for signal in read_only_signals):
                    return True
    except Exception:
        return False
    return False


def _tool_file_path(tool_input: dict[str, Any]) -> Path | None:
    raw = tool_input.get("file_path") or tool_input.get("notebook_path")
    return Path(raw).expanduser() if isinstance(raw, str) and raw else None


def _cwd_from_hook(data: dict[str, Any]) -> Path | None:
    raw = data.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(raw).expanduser() if isinstance(raw, str) and raw else None


def _is_allowed_repo_plan_file(path: Path, cwd: Path | None) -> bool:
    if cwd is None or path.suffix.lower() not in {".md", ".markdown"}:
        return False
    return _is_under(path, cwd / "docs" / "superpowers" / "plans")


def _is_allowed_plan_file(path: Path, plan_path: Path | None, cwd: Path | None) -> bool:
    plans_root = Path.home() / ".claude" / "plans"
    if plan_path is not None:
        try:
            if path.resolve() == plan_path.resolve():
                return True
        except Exception:
            pass
    if path.suffix.lower() in {".md", ".markdown"} and _is_under(path, plans_root):
        return True
    return _is_allowed_repo_plan_file(path, cwd)


def _strip_heredoc_bodies(command: str) -> str:
    lines = command.splitlines()
    stripped: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped.append(line)
        match = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if not match:
            index += 1
            continue

        delimiter = match.group(1)
        index += 1
        while index < len(lines) and lines[index].strip() != delimiter:
            index += 1
        if index < len(lines):
            stripped.append(delimiter)
            index += 1
    return "\n".join(stripped)


def _bash_has_mutation(command: str) -> bool:
    shell_surface = _strip_heredoc_bodies(command)
    if OUTPUT_REDIRECT_RE.search(shell_surface):
        return True
    if any(re.search(pattern, shell_surface, flags=re.IGNORECASE) for pattern in MUTATING_BASH_PATTERNS):
        return True
    return any(re.search(pattern, command, flags=re.IGNORECASE | re.DOTALL) for pattern in MUTATING_SCRIPT_PATTERNS)


def _task_id_is_agent_mailbox(task_id: Any) -> bool:
    return isinstance(task_id, str) and "@session-" in task_id


def _missing_required_tool_args(tool_name: str, tool_input: dict[str, Any]) -> list[str]:
    missing = []
    for key in REQUIRED_TOOL_ARGS.get(tool_name, ()):
        value = tool_input.get(key)
        if not isinstance(value, str) or not value:
            missing.append(key)
    return missing


def _agent_text(tool_input: dict[str, Any]) -> str:
    fields = []
    for key in ("description", "name", "prompt", "subagent_type", "model"):
        value = tool_input.get(key)
        if isinstance(value, str):
            fields.append(value)
    return "\n".join(fields).lower()


def _agent_prompt_is_read_only(tool_input: dict[str, Any]) -> bool:
    text = _agent_text(tool_input)
    return any(
        signal in text
        for signal in (
            "read-only",
            "do not edit",
            "do not modify",
            "no edits",
            "without making changes",
            "explore",
            "scout",
            "map",
            "lookup",
            "find",
        )
    )


def _known_context_exceeds_spark(text: str, cwd: Path | None) -> bool:
    if cwd is None:
        return False

    total = 0
    for raw in set(PATH_TOKEN_RE.findall(text)):
        raw = raw.rstrip(").,;:'\"`")
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = cwd / path

        matches: list[Path]
        if any(char in raw for char in "*?["):
            try:
                matches = [candidate for candidate in path.parent.glob(path.name) if candidate.is_file()]
            except Exception:
                matches = []
        else:
            matches = [path] if path.is_file() else []

        for candidate in matches:
            try:
                size = candidate.stat().st_size
            except Exception:
                continue
            if size > SPARK_CONTEXT_MAX_BYTES:
                return True
            total += size
            if total > SPARK_CONTEXT_MAX_BYTES:
                return True
    return False


def _agent_prompt_needs_large_context(tool_input: dict[str, Any], cwd: Path | None) -> bool:
    text = _agent_text(tool_input)
    if _known_context_exceeds_spark(text, cwd):
        return True
    return any(
        signal in text
        for signal in (
            "very thorough",
            "comprehensive",
            "entire repo",
            "whole repo",
            "large context",
            "large file",
            "many files",
            "multiple directories",
            "cross-module",
            "exceeds spark",
            "over 128k",
            "over 128 k",
        )
    )


def _agent_prompt_needs_sonnet_explore(tool_input: dict[str, Any]) -> bool:
    text = _agent_text(tool_input)
    return any(
        signal in text
        for signal in (
            "architecture judgment",
            "deep reasoning",
            "adversarial",
            "review",
            "implementation",
            "refactor",
            "security",
        )
    )


def _route_plan_agent(tool_input: dict[str, Any], cwd: Path | None) -> dict[str, Any] | None:
    if not _agent_prompt_is_read_only(tool_input):
        return None

    target_type = "spark-explorer"
    target_model: str | None = _spark_agent_model()
    if _agent_prompt_needs_sonnet_explore(tool_input):
        target_type = "Explore"
        target_model = _explore_agent_model()
    elif _agent_prompt_needs_large_context(tool_input, cwd):
        if _is_glm_codex_session():
            target_type = _mini_explorer_agent_type()
            target_model = None
        else:
            target_type = "Explore"
            target_model = _explore_agent_model()

    if tool_input.get("subagent_type") == target_type and (
        target_model is None or tool_input.get("model") == target_model
    ):
        return None

    updated = dict(tool_input)
    updated["subagent_type"] = target_type
    if target_model is None:
        updated.pop("model", None)
    else:
        updated["model"] = target_model
    return updated


def _normalize_named_agent_model(tool_input: dict[str, Any]) -> dict[str, Any] | None:
    """Keep explicit model overrides from defeating named agent routing."""
    if not _is_glm_codex_session():
        return None

    agent_type = tool_input.get("subagent_type")
    if not isinstance(agent_type, str):
        return None

    target_model: str | None
    if agent_type in SPARK_AGENT_TYPES:
        target_model = _spark_agent_model()
    elif agent_type == _mini_explorer_agent_type():
        target_model = None
    elif agent_type in SONNET_AGENT_TYPES:
        target_model = _explore_agent_model()
    else:
        return None

    if target_model is None:
        if "model" not in tool_input:
            return None
        updated = dict(tool_input)
        updated.pop("model", None)
        return updated

    if tool_input.get("model") == target_model:
        return None
    updated = dict(tool_input)
    updated["model"] = target_model
    return updated


def main() -> int:
    data = _load_hook_input()
    if data.get("hook_event_name") != "PreToolUse":
        return 0

    tool_name = data.get("tool_name")
    tool_input = data.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 0

    named_agent_input = _normalize_named_agent_model(tool_input) if tool_name == "Agent" else None

    if tool_name == "TaskOutput" and _task_id_is_agent_mailbox(tool_input.get("task_id")):
        return _deny(
            "TaskOutput cannot read Agent mailbox IDs such as *@session-*. "
            "Agent results arrive as <agent-result> or <task-notification> "
            "blocks in the parent transcript.",
            "Do not retry TaskOutput with Agent mailbox names or agent_id values. "
            "Use the <agent-result> or <task-notification> content already in "
            "the transcript, or continue with available evidence.",
        )

    transcript_raw = data.get("transcript_path")
    if not isinstance(transcript_raw, str) or not transcript_raw:
        if named_agent_input is not None:
            return _allow(
                "Normalized named GLM/Codex Agent model route.",
                "Named agents must stay on their configured lane: Spark agents use "
                "Haiku/Spark, Mini relies on its custom-agent model, and Codex "
                "worker/reviewer/verifier agents use Sonnet/GPT-5.5.",
                named_agent_input,
            )
        return 0
    transcript_path = Path(transcript_raw).expanduser()
    plan_path, in_plan_mode = _read_latest_plan_state(transcript_path)
    in_read_only_sidechain = _transcript_is_read_only_sidechain(transcript_path)
    if not in_plan_mode and not in_read_only_sidechain:
        if named_agent_input is not None:
            return _allow(
                "Normalized named GLM/Codex Agent model route.",
                "Named agents must stay on their configured lane: Spark agents use "
                "Haiku/Spark, Mini relies on its custom-agent model, and Codex "
                "worker/reviewer/verifier agents use Sonnet/GPT-5.5.",
                named_agent_input,
            )
        return 0

    missing_args = _missing_required_tool_args(tool_name, tool_input)
    if missing_args:
        return _deny(
            f"{tool_name} tool call is missing required argument(s): {', '.join(missing_args)}.",
            "Do not retry the same empty or schema-invalid tool call. If this is a "
            "Spark/Haiku scout, stop that scout and report: Spark tool-call failure; "
            "retry this bounded slice with mini-explorer/gpt-5.4-mini or handle it "
            "locally with valid tool arguments.",
        )

    if in_plan_mode and tool_name == "TaskOutput":
        return _deny(
            "Plan mode does not poll Agent results with TaskOutput. Agent mailbox "
            "results arrive as <agent-result> or <task-notification> blocks in "
            "the parent transcript. Synthesize from those blocks; do not call "
            "TaskOutput with agent names or agent_id values."
        )

    if tool_name == "Agent":
        routed_input = _route_plan_agent(tool_input, _cwd_from_hook(data)) if in_plan_mode else None
        if routed_input is None:
            routed_input = named_agent_input
        return _allow(
            "Plan/read-only context allows read-only Agent fanout.",
            "Use agents only for bounded evidence gathering. Do not call TaskOutput "
            "for Agent mailbox names; synthesize results from <agent-result> or "
            "<task-notification> blocks and keep final plan synthesis in the "
            "parent session.",
            routed_input,
        )

    if tool_name in MUTATING_FILE_TOOLS:
        file_path = _tool_file_path(tool_input)
        if file_path is not None and _is_allowed_plan_file(file_path, plan_path, _cwd_from_hook(data)):
            return _allow("Plan mode allows writes to the active plan file or repo plan document.")
        return _deny(
            f"Plan mode blocks {tool_name} outside the active plan file. "
            "Use ExitPlanMode to present the plan before implementation."
        )

    if tool_name == "Bash":
        command = tool_input.get("command")
        if isinstance(command, str) and _bash_has_mutation(command):
            return _deny("Protected planning/read-only mode blocks mutating Bash commands.")
        return _allow("Plan/read-only context allows read-only Bash exploration.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
