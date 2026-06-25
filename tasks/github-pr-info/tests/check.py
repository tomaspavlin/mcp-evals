import os
from pathlib import Path

from rewardkit import criterion
from rewardkit.criteria._trajectory import collect_tool_calls, load_trajectory

TRAJECTORY_PATH = "/logs/agent/trajectory.json"

import json as _json
APP = "github"
_connectors = _json.loads(os.environ.get("CONNECTOR_EVALS_CONNECTORS_JSON") or "{}")
EXPECTED_CONNECTOR = _connectors.get(APP) or os.environ.get("CONNECTOR_EVALS_CONNECTOR") or None
# `skill` connector is CLI usage + extra prompt; match like cli.
if EXPECTED_CONNECTOR in ("skill", "cli+skill"):
    EXPECTED_CONNECTOR = "cli"


def _tool_calls() -> list[dict]:
    data = load_trajectory(TRAJECTORY_PATH)
    return collect_tool_calls(data) if data else []


# Connector matching mirrored from src/connector_evals/metrics.py (cannot import the
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


def _matches_connector(tc: dict, connector: str) -> bool:
    name = (tc.get("function_name") or "").lower()
    args = tc.get("arguments") or {}
    cmd = ((args.get("command") or args.get("cmd")) or "").lstrip()
    if connector == "mcp":
        return name.startswith(MCP_NAME_PREFIXES) or _normalize_mcp_tool(name) in GITHUB_MCP_TOOLS
    if connector == "cli":
        return name in SHELL_TOOLS and cmd.startswith("gh ")
    if connector == "mcpc":
        return name in SHELL_TOOLS and cmd.startswith("mcpc ")
    return False


def _log_summary() -> None:
    calls = _tool_calls()
    print(f"[verifier] expected_connector={EXPECTED_CONNECTOR!r} tool_calls={len(calls)}")
    for i, tc in enumerate(calls):
        name = tc.get("function_name", "")
        args = tc.get("arguments") or {}
        cmd = args.get("command") or args.get("cmd")
        snippet = cmd if cmd else str(args)
        match = "*" if EXPECTED_CONNECTOR and _matches_connector(tc, EXPECTED_CONNECTOR) else " "
        print(f"[verifier] {match} {i:3d} {name}  {str(snippet)[:140]}")


_log_summary()


@criterion(description=f"agent used expected connector ({EXPECTED_CONNECTOR or 'n/a'})")
def used_expected_connector(workspace: Path) -> bool:
    if not EXPECTED_CONNECTOR:
        return True
    return any(_matches_connector(tc, EXPECTED_CONNECTOR) for tc in _tool_calls())
