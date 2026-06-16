import os
from pathlib import Path

from rewardkit import criterion
from rewardkit.criteria._trajectory import collect_tool_calls, load_trajectory

TRAJECTORY_PATH = "/logs/agent/trajectory.json"

import json as _json
CONNECTOR = "github"
_channels = _json.loads(os.environ.get("MCP_EVALS_CHANNELS_JSON") or "{}")
EXPECTED_CHANNEL = _channels.get(CONNECTOR) or os.environ.get("MCP_EVALS_CHANNEL") or None
# `skill` channel is CLI usage + extra prompt; match like cli.
if EXPECTED_CHANNEL == "skill":
    EXPECTED_CHANNEL = "cli"


def _tool_calls() -> list[dict]:
    data = load_trajectory(TRAJECTORY_PATH)
    return collect_tool_calls(data) if data else []


# Channel matching mirrored from src/mcp_evals/metrics.py (cannot import the
# package inside the verifier container); keep both in sync manually.
#
# GitHub MCP tool allowlist for harnesses that strip the server prefix from
# tool names (codex: "pull_request_read"). claude-code preserves a
# "mcp__github__" prefix, opencode a "github_" prefix; both are caught by the
# prefix check directly. This list only needs to cover the prefix-strippers.
# Extend when surfacing new GitHub MCP tools in evals.
GITHUB_MCP_TOOLS = {
    "pull-request-read",
    "pull-request-list",
    "issue-read",
    "issue-list",
    "list-pull-requests",
    "list-issues",
    "get-pull-request",
    "get-issue",
    "list-commits",
    "get-commit",
    "list-releases",
    "get-latest-release",
    "list-branches",
    "list-tags",
    "search-issues",
    "search-pull-requests",
    "search-code",
    "search-repositories",
    "get-file-contents",
    "get-me",
}

MCP_NAME_PREFIXES = ("github_", "github-", "mcp__github__")
# Shell tool names per harness: opencode "bash", claude-code "Bash" (lowercased
# before comparison), codex "exec_command" (command in the "cmd" argument).
SHELL_TOOLS = {"bash", "exec_command", "shell", "run_terminal_cmd", "local_shell"}


def _normalize_mcp_tool(name: str) -> str:
    for prefix in MCP_NAME_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", "-")


def _matches_channel(tc: dict, channel: str) -> bool:
    name = (tc.get("function_name") or "").lower()
    args = tc.get("arguments") or {}
    cmd = ((args.get("command") or args.get("cmd")) or "").lstrip()
    if channel == "mcp":
        return name.startswith(MCP_NAME_PREFIXES) or _normalize_mcp_tool(name) in GITHUB_MCP_TOOLS
    if channel == "cli":
        return name in SHELL_TOOLS and cmd.startswith("gh ")
    return False


def _log_summary() -> None:
    calls = _tool_calls()
    print(f"[verifier] expected_channel={EXPECTED_CHANNEL!r} tool_calls={len(calls)}")
    for i, tc in enumerate(calls):
        name = tc.get("function_name", "")
        args = tc.get("arguments") or {}
        cmd = args.get("command") or args.get("cmd")
        snippet = cmd if cmd else str(args)
        match = "*" if EXPECTED_CHANNEL and _matches_channel(tc, EXPECTED_CHANNEL) else " "
        print(f"[verifier] {match} {i:3d} {name}  {str(snippet)[:140]}")


_log_summary()


@criterion(description=f"agent used expected channel ({EXPECTED_CHANNEL or 'n/a'})")
def used_expected_channel(workspace: Path) -> bool:
    if not EXPECTED_CHANNEL:
        return True
    return any(_matches_channel(tc, EXPECTED_CHANNEL) for tc in _tool_calls())
