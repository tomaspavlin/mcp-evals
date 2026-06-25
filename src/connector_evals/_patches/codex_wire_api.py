"""Monkey-patch for Harbor's codex agent: route through a custom
`openrouter` model provider so MCP tools survive the OpenRouter setup.

# Problem (MCP integrations only)

Codex CLI 0.139 uses OpenAI's Responses API over WebSocket. With
`OPENAI_BASE_URL=https://openrouter.ai/api/v1` (the project default, see
`.env`), codex tries `wss://openrouter.ai/api/v1/responses` which 404s
because OpenRouter does not implement the Responses API at that path.
Codex retries 5 times, then falls back to a degraded mode. In that
fallback, MCP tool definitions are not re-registered with the model,
so the agent emits a single commentary message ("I'm going to look
up..."), the codex CLI fires `turn.completed` with zero tool calls,
and every criterion fails.

The failure was MCP-only:
- codex + CLI integration: 1.000 (shell tools survive the fallback)
- codex + skill integration: 1.000 (no tools required at runtime)
- codex + MCP integration: 0.000 (MCP tools never reach the model)

Symptom signature in the trial logs:
- agent/codex.txt: 5x `wss://openrouter.ai/api/v1/responses 404 Not Found`
- rollout jsonl: `turn.completed` immediately after one `agent_message`
- verifier stdout: `tool_calls=0`

# Fix

Append to `$CODEX_HOME/config.toml`:

  model_provider = "openrouter"
  disable_response_storage = true

  [model_providers.openrouter]
  name = "OpenRouter"
  base_url = "https://openrouter.ai/api/v1"
  wire_api = "responses"

The top-level `model_provider` and `disable_response_storage` MUST come
before the `[model_providers.openrouter]` table; otherwise TOML scoping
makes them sub-keys of that table and codex keeps using its default
`openai` provider. The featurebench parity adapter applies the same
pattern via a Dockerfile wrapper (see harbor
`adapters/featurebench/template/environment/Dockerfile`); doing it as a
monkey-patch keeps the fix in one place across all integrations.

Codex CLI 0.139 deprecated `wire_api = "chat"` and only accepts
`wire_api = "responses"` at config-load time (see codex issue 7782).
`disable_response_storage = true` is required when the provider does
not implement the stored-response storage path (any provider other
than OpenAI's own endpoint).

This patch chains on top of `codex_mcp_env.py`: it calls the previously
installed `_build_register_mcp_servers_command` and appends its own
config block, so both env-forwarding for MCP servers and the provider
override compose. Import order in `connector_evals/__init__.py` matters and
is enforced alphabetically (codex_mcp_env before codex_wire_api).

TODO: remove when upstream harbor adds model-provider configuration to
its codex agent.
"""

from harbor.agents.installed.codex import Codex

_prev_build_register_mcp_servers_command = Codex._build_register_mcp_servers_command


def _build_register_mcp_servers_command(self: Codex) -> str | None:
    base = _prev_build_register_mcp_servers_command(self)
    base_url = self._get_env("OPENAI_BASE_URL") or ""
    if "openrouter.ai" not in base_url:
        return base

    # Top-level keys must come before any [section] header in TOML, else they
    # get scoped under the most recent section. Order here matters.
    config_block = (
        'model_provider = "openrouter"\n'
        "disable_response_storage = true\n"
        "\n"
        "[model_providers.openrouter]\n"
        'name = "OpenRouter"\n'
        f'base_url = "{base_url}"\n'
        'wire_api = "responses"\n'
    )
    addendum = (
        'cat >>"$CODEX_HOME/config.toml" <<WIRE_TOML\n'
        f"{config_block}"
        "WIRE_TOML"
    )
    if base is None:
        return addendum
    # Put the provider override BEFORE the MCP server section in the appended
    # heredoc, so the top-level keys aren't scoped into [mcp_servers.*].
    return addendum + "\n" + base


Codex._build_register_mcp_servers_command = _build_register_mcp_servers_command
