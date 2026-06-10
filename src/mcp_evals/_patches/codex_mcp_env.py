"""Monkey-patch for Harbor's codex agent (harbor 0.13.1, upstream unfixed).

Upstream `Codex._build_register_mcp_servers_command` writes only `command`/`url`
to `$CODEX_HOME/config.toml` and never an `env = { ... }` block. Codex CLI does
not inherit parent env into MCP child processes, so MCP servers that need
secrets (APIFY_TOKEN etc.) see an empty environment and fail silently at
startup.

TODO: remove when fixed in harbor
"""

import shlex

from harbor.agents.installed.codex import Codex

# server name → env-var names to forward into the codex MCP child process.
# Keep in sync with integrations/<name>/environment_env. Add a row per new
# integration that wraps a remote MCP behind auth.
MCP_SERVER_ENV: dict[str, list[str]] = {
    "apify": ["APIFY_TOKEN"],
}


def _build_register_mcp_servers_command(self: Codex) -> str | None:
    if not self.mcp_servers:
        return None

    blocks: list[str] = []
    for server in self.mcp_servers:
        lines = [f"[mcp_servers.{server.name}]"]
        if server.transport == "stdio":
            cmd_parts = [server.command] + server.args if server.command else []
            lines.append(f'command = "{shlex.join(cmd_parts)}"')
        else:
            lines.append(f'url = "{server.url}"')
        env_vars = MCP_SERVER_ENV.get(server.name, [])
        if env_vars:
            pairs = ", ".join(f'{name} = "${{{name}}}"' for name in env_vars)
            lines.append(f"env = {{ {pairs} }}")
        blocks.append("\n".join(lines))

    body = "\n\n".join(blocks) + "\n"
    return f'cat >>"$CODEX_HOME/config.toml" <<MCP_TOML\n{body}MCP_TOML'


Codex._build_register_mcp_servers_command = _build_register_mcp_servers_command
