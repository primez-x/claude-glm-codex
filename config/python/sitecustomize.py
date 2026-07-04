"""Runtime patches for the claude-glm-codex LiteLLM gateway.

This file is loaded only by the hybrid wrapper via PYTHONPATH. It keeps the
ChatGPT/Codex route compatible with Claude Code's Anthropic-shaped system
content without modifying the global Claude or claude-glm launchers.
"""

from __future__ import annotations

import os
from typing import Any


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            text = _content_to_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text
        nested = content.get("content")
        if nested is not None:
            return _content_to_text(nested)
        return ""
    return str(content)


def _install_chatgpt_system_message_patch() -> None:
    try:
        from litellm.completion_extras.litellm_responses_transformation.transformation import (
            LiteLLMResponsesTransformationHandler,
        )
    except Exception:
        return

    if getattr(
        LiteLLMResponsesTransformationHandler,
        "_claude_glm_codex_system_patch",
        False,
    ):
        return

    original = (
        LiteLLMResponsesTransformationHandler.convert_chat_completion_messages_to_responses_api
    )

    def patched_convert(self: Any, messages: list[Any]) -> tuple[list[Any], str | None]:
        kept_messages: list[Any] = []
        instruction_parts: list[str] = []

        for message in messages:
            if not isinstance(message, dict):
                kept_messages.append(message)
                continue

            role = message.get("role")
            if role in {"system", "developer"}:
                text = _content_to_text(message.get("content"))
                if text:
                    instruction_parts.append(text)
                continue

            kept_messages.append(message)

        input_items, instructions = original(self, kept_messages)

        if instructions:
            instruction_parts.append(instructions)

        joined_instructions = "\n\n".join(
            part for part in instruction_parts if part.strip()
        )
        return input_items, joined_instructions or None

    LiteLLMResponsesTransformationHandler.convert_chat_completion_messages_to_responses_api = (  # type: ignore[method-assign]
        patched_convert
    )
    LiteLLMResponsesTransformationHandler._claude_glm_codex_system_patch = True


def _install_advisor_streaming_subcall_patch() -> None:
    try:
        from litellm.llms.anthropic.experimental_pass_through.messages.interceptors import (
            advisor,
        )
        from litellm.llms.anthropic.experimental_pass_through.messages.agentic_streaming_iterator import (
            AgenticAnthropicStreamingIterator,
        )
    except Exception:
        return

    if getattr(advisor, "_claude_glm_codex_streaming_advisor_patch", False):
        return

    original = advisor._call_messages_handler

    def model_from_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
        model = kwargs.get("model")
        if model is None and args:
            model = args[0]
        return str(model or "advisor")

    def needs_streaming_subcall(model: str, kwargs: dict[str, Any]) -> bool:
        if str(kwargs.get("stream", "")).lower() == "true":
            return False
        if str(kwargs.get("custom_llm_provider") or "").lower() == "anthropic":
            return False
        normalized = model.lower()
        return (
            normalized in {"sonnet", "haiku"}
            or normalized.startswith("gpt-")
            or "codex" in normalized
            or "chatgpt/" in normalized
        )

    async def collect_streaming_response(stream: Any) -> dict[str, Any]:
        raw_chunks: list[bytes] = []
        if hasattr(stream, "__aiter__"):
            async for chunk in stream:
                if isinstance(chunk, bytes):
                    raw_chunks.append(chunk)
                elif isinstance(chunk, str):
                    raw_chunks.append(chunk.encode())
                else:
                    raw_chunks.append(str(chunk).encode())
        else:
            for chunk in stream:
                if isinstance(chunk, bytes):
                    raw_chunks.append(chunk)
                elif isinstance(chunk, str):
                    raw_chunks.append(chunk.encode())
                else:
                    raw_chunks.append(str(chunk).encode())

        rebuilt = AgenticAnthropicStreamingIterator._rebuild_anthropic_response_from_sse(
            raw_chunks
        )
        if rebuilt is None:
            raise ValueError("Unable to rebuild Anthropic response from advisor stream")
        return rebuilt

    async def patched_call_messages_handler(*args: Any, **kwargs: Any) -> Any:
        model = model_from_call(args, kwargs)
        if not needs_streaming_subcall(model, kwargs):
            return await original(*args, **kwargs)

        stream_kwargs = dict(kwargs)
        stream_kwargs["stream"] = True
        stream = await original(*args, **stream_kwargs)
        return await collect_streaming_response(stream)

    advisor._call_messages_handler = patched_call_messages_handler
    advisor._claude_glm_codex_streaming_advisor_patch = True


def _install_cross_model_advisor_patch() -> None:
    try:
        from litellm.llms.anthropic.experimental_pass_through.messages.interceptors import (
            advisor,
        )
        from litellm.types.llms.anthropic import ANTHROPIC_ADVISOR_TOOL_TYPE
    except Exception:
        return

    handler_cls = advisor.AdvisorOrchestrationHandler
    if getattr(handler_cls, "_claude_glm_codex_cross_advisor_patch", False):
        return

    original_handle = handler_cls.handle

    disabled_values = {"0", "false", "False", "no"}

    def alias_normalization_enabled() -> bool:
        return (
            os.environ.get("CLAUDE_GLM_CODEX_ADVISOR_ALIAS_NORMALIZATION", "1")
            not in disabled_values
        )

    def normalized_model_name(model: str) -> str:
        normalized = str(model or "").lower()
        if normalized.endswith("[1m]"):
            normalized = normalized[:-4]
        return normalized

    def is_fable_alias(model: str) -> bool:
        return normalized_model_name(model) in {
            "fable",
            "glm-codex-hybrid",
            "claude-fable-5",
        }

    def is_glm_alias(model: str) -> bool:
        normalized = normalized_model_name(model)
        return normalized == "opus" or "glm" in normalized or is_fable_alias(model)

    def is_spark_alias(model: str) -> bool:
        normalized = normalized_model_name(model)
        return (
            normalized == "haiku"
            or "spark" in normalized
            or normalized.startswith("gpt-5.3-codex")
        )

    def is_sonnet_alias(model: str) -> bool:
        normalized = normalized_model_name(model)
        return (
            normalized == "sonnet"
            or normalized.startswith("gpt-5.5")
            or "sonnet" in normalized
        )

    def is_chatgpt_route(model: str) -> bool:
        return normalized_model_name(model).startswith("chatgpt/")

    def glm_provider_model(model: str) -> str:
        normalized = normalized_model_name(model)
        if normalized == "opus" or is_fable_alias(model):
            return os.environ.get("CLAUDE_GLM_UPSTREAM_OPUS_MODEL", "anthropic/glm-5.2")

        stripped = str(model or os.environ.get("CLAUDE_GLM_UPSTREAM_OPUS_MODEL", "glm-5.2"))
        if stripped.endswith("[1m]"):
            stripped = stripped[:-4]
        if "/" not in stripped:
            stripped = f"anthropic/{stripped}"
        return stripped

    def apply_glm_route(tool: dict[str, Any], model: str) -> dict[str, Any]:
        updated = dict(tool)
        updated["model"] = glm_provider_model(model)

        api_base = os.environ.get("CLAUDE_GLM_UPSTREAM_BASE_URL")
        api_key = os.environ.get("CLAUDE_GLM_UPSTREAM_AUTH_TOKEN")
        if api_base:
            updated["api_base"] = api_base
        if api_key:
            updated["api_key"] = api_key
        return updated

    def apply_chatgpt_route(tool: dict[str, Any], model: str) -> dict[str, Any]:
        updated = dict(tool)
        normalized = normalized_model_name(model)

        if is_chatgpt_route(model):
            updated["model"] = model
        elif is_spark_alias(model):
            updated["model"] = os.environ.get(
                "CLAUDE_GLM_CODEX_SPARK_ADVISOR_MODEL",
                "chatgpt/gpt-5.3-codex-spark",
            )
        else:
            updated["model"] = os.environ.get(
                "CLAUDE_GLM_CODEX_SONNET_ADVISOR_MODEL",
                "chatgpt/gpt-5.5",
            )

        if normalized.startswith("chatgpt/") or is_spark_alias(model) or is_sonnet_alias(model):
            updated.pop("api_base", None)
            updated.pop("api_key", None)
        return updated

    def normalize_advisor_tool(tool: dict[str, Any]) -> dict[str, Any]:
        model = str(tool.get("model") or "")
        if is_fable_alias(model):
            return dict(tool)
        if is_glm_alias(model):
            return apply_glm_route(tool, model)
        if is_chatgpt_route(model) or is_spark_alias(model) or is_sonnet_alias(model):
            return apply_chatgpt_route(tool, model)
        return dict(tool)

    def is_codex_model(model: str) -> bool:
        normalized = normalized_model_name(model)
        return (
            normalized in {"sonnet", "haiku"}
            or normalized.startswith("gpt-")
            or "codex" in normalized
            or "chatgpt/" in normalized
        )

    def is_glm_model(model: str) -> bool:
        return is_glm_alias(model)

    def gpt_advisor_tool(tool: dict[str, Any]) -> dict[str, Any]:
        updated = dict(tool)
        updated["model"] = os.environ.get("CLAUDE_GLM_CODEX_GLM_ADVISOR_MODEL", "sonnet")
        return normalize_advisor_tool(updated)

    def glm_advisor_tool(tool: dict[str, Any]) -> dict[str, Any]:
        updated = dict(tool)
        updated["model"] = os.environ.get("CLAUDE_GLM_CODEX_CODEX_ADVISOR_MODEL", "opus")
        return normalize_advisor_tool(updated)

    def advisor_tool_for_executor(model: str, tool: dict[str, Any]) -> dict[str, Any]:
        advisor_model = str(tool.get("model") or "")
        if is_fable_alias(advisor_model):
            if is_codex_model(model):
                return glm_advisor_tool(tool)
            if is_glm_model(model):
                return gpt_advisor_tool(tool)
            return gpt_advisor_tool(tool)
        return normalize_advisor_tool(tool)

    def route_advisor_tool(model: str, tools: Any) -> Any:
        if not alias_normalization_enabled() or not isinstance(tools, list):
            return tools

        routed_tools: list[Any] = []
        changed = False
        for tool in tools:
            if (
                isinstance(tool, dict)
                and tool.get("type") == ANTHROPIC_ADVISOR_TOOL_TYPE
            ):
                updated = advisor_tool_for_executor(model, tool)
                routed_tools.append(updated)
                changed = changed or updated != tool
            else:
                routed_tools.append(tool)

        return routed_tools if changed else tools

    async def patched_handle(self: Any, *, model: str, tools: Any, **kwargs: Any) -> Any:
        return await original_handle(
            self,
            model=model,
            tools=route_advisor_tool(model, tools),
            **kwargs,
        )

    handler_cls.handle = patched_handle
    handler_cls._claude_glm_codex_cross_advisor_patch = True


_install_chatgpt_system_message_patch()
_install_advisor_streaming_subcall_patch()
_install_cross_model_advisor_patch()
