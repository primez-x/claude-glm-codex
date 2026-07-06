# claude-glm-codex

`claude-glm-codex` is a public, copyable setup for running Claude Code as a GLM-led, GPT/Codex-executed hybrid through a local LiteLLM gateway.

This repo intentionally ships templates, launchers, hooks, prompts, and verification scripts only. It does not include provider env files, auth JSON, private keys, transcripts, tokens, or machine-local caches.

## What Is Included

- `bin/claude-glm-codex` - Claude Code launcher for the hybrid GLM/Codex workflow.
- `bin/claude-glm-codex-litellm` - LiteLLM gateway bootstrapper used by the launcher.
- `config/litellm/claude-glm-codex.yaml` - sanitized LiteLLM model routes.
- `config/claude/agents.json` - Spark, GPT-5.4-mini, and GPT-5.5 agents for exploration, formatting, checking, summarization, implementation, review, and verification.
- `config/python/sitecustomize.py` - LiteLLM compatibility shim for ChatGPT Responses system-message handling, advisor streaming, and cross-model advisor routing.
- `prompts/fable-provider-native-system-glm-codex.md` - provider-native GLM/Codex system prompt.
- `prompts/claude-glm-codex-subagents.md` - appended delegation policy for agents and advisor routing.
- `hooks/` - shared Claude plan-mode, plan-file, and persisted plan-goal hooks.
- `scripts/install.sh` - idempotent local installer.
- `scripts/doctor.sh` - local installation checks.
- `scripts/verify-release.sh` - maintainer verification before publishing.

## Requirements

- Claude Code CLI available as `claude`.
- LiteLLM CLI available as `litellm`.
- Python 3.
- `curl`, `pgrep`, and `tmux` if you want automatic tmux session management.
- A local GLM env file at `~/.config/claude-glm/env` containing your private provider values. This file is never committed.
- LiteLLM ChatGPT provider auth for the bundled `chatgpt/...` routes. The gateway can sync a readable `~/.codex/auth.json` token into LiteLLM's ChatGPT auth location when `CLAUDE_GLM_CODEX_SYNC_CODEX_AUTH=1`.

Example private env file shape:

```bash
ANTHROPIC_AUTH_TOKEN="your-private-token"
ANTHROPIC_BASE_URL="https://your-provider.example"
ANTHROPIC_DEFAULT_OPUS_MODEL="glm-5.2[1m]"
```

## Quick Start

```bash
git clone git@github.com:primez-x/claude-glm-codex.git
cd claude-glm-codex
./scripts/verify-release.sh
./scripts/install.sh --force
claude-glm-codex
```

The installer copies launchers into `~/.local/bin`, installs the LiteLLM config into `~/.config/litellm/claude-glm-codex.yaml`, installs agents into `~/.config/claude-glm-codex/agents.json`, installs the gateway shim into `~/.local/share/claude-glm-codex/sitecustomize.py`, installs prompts into `~/.claude/prompts`, installs Claude hooks into `~/.claude/hooks`, and registers the hooks in `~/.claude/settings.json`.

## Model Routing

The main thread defaults to GLM through the Opus slot. GPT-5.5 is exposed through Sonnet-style routes for heavier Codex delegation. GPT-5.3 Codex Spark is exposed through Haiku-style routes for the fastest bounded work. GPT-5.4-mini remains available as an explicit route and as `mini-explorer`, which can fan out multiple Spark scouts for broader read-only exploration or take over when a Spark slice fails tool-call validation.

The visible smart advisor route is `glm-codex-hybrid`; legacy `fable` aliases are kept hidden for compatibility. With the hybrid advisor selected, GLM executor calls are advised by GPT-5.5, while GPT/Spark executor calls are advised by GLM. Explicit advisor selections such as `sonnet`, `haiku`, or `opus` are honored.

## Safety Defaults

- The launcher reads provider secrets from `~/.config/claude-glm/env` at runtime and exports them into the local LiteLLM process. The env file is not installed or committed.
- Plan mode is guarded by a `PreToolUse` hook that fails closed for mutations while allowing bounded read-only exploration.
- Accepted-plan implementation is guarded by persisted Claude goal hooks under `~/.claude/goals`; the Stop hook blocks completion until the final answer contains a Plan Gap Check or a clear blocked-state report.
- `.gitignore` excludes auth files, env files, transcripts, key material, token caches, logs, and common runtime state.

## Verification

Run this before publishing changes:

```bash
./scripts/verify-release.sh
```

Run this after installing on a user machine:

```bash
./scripts/doctor.sh
```
