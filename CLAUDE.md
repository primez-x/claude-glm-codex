# Claude Code Instructions for This Repository

This repository is a public release package for the `claude-glm-codex` hybrid launcher and supporting config.

## Public-Repo Safety

- Never commit environment files, provider auth JSON, private keys, tokens, transcripts, logs, or machine-local caches.
- Keep examples credential-free. Use environment variable names such as `ANTHROPIC_AUTH_TOKEN`, never real values.
- Do not copy `~/.config/claude-glm/env` into this repo.
- Run `./scripts/verify-release.sh` before committing or pushing.
- If installer behavior changed, also run `./scripts/install.sh --dry-run` and `./scripts/doctor.sh`.

## Scope

- Launchers live in `bin/`.
- LiteLLM routes live in `config/litellm/`.
- Claude agents live in `config/claude/`.
- Gateway runtime patches live in `config/python/`.
- Provider-native prompts live in `prompts/`.
- Claude hooks live in `hooks/`.

Prefer durable, user-copyable defaults over machine-local behavior. If a local workflow depends on private services, provider-specific token caches, or personal accounts, document it as an opt-in environment variable rather than making it the default.
