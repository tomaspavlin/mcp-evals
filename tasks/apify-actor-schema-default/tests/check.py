import os
from pathlib import Path

from rewardkit import criterion
from rewardkit.criteria._trajectory import collect_tool_calls, load_trajectory

EXPECTED_DEFAULT = "20"
TRAJECTORY_PATH = "/logs/agent/trajectory.json"

import json as _json
APP = "apify"
_connectors = _json.loads(os.environ.get("MCP_EVALS_CONNECTORS_JSON") or "{}")
EXPECTED_CONNECTOR = _connectors.get(APP) or os.environ.get("MCP_EVALS_CONNECTOR") or None
# `skill` connector is CLI usage + extra prompt; match like cli.
if EXPECTED_CONNECTOR in ("skill", "cli+skill"):
    EXPECTED_CONNECTOR = "cli"


def _tool_calls() -> list[dict]:
    data = load_trajectory(TRAJECTORY_PATH)
    return collect_tool_calls(data) if data else []


# Connector matching mirrored from src/mcp_evals/metrics.py (cannot import the
# package inside the verifier container); keep both in sync manually.
APIFY_MCP_TOOLS = {
    "fetch-actor-details",
    "search-actors",
    "call-actor",
    "add-actor",
    "fetch-apify-docs",
    "search-apify-docs",
    "get-actor-run",
    "get-dataset-items",
    "get-key-value-store-record",
    "abort-actor-run",
}

MCP_NAME_PREFIXES = ("apify_", "apify-", "mcp__apify__")
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
        return name.startswith(MCP_NAME_PREFIXES) or _normalize_mcp_tool(name) in APIFY_MCP_TOOLS
    if connector == "cli":
        return name in SHELL_TOOLS and cmd.startswith("apify ")
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


@criterion
def default_file_exists(workspace: Path) -> bool:
    return (workspace / "default.txt").is_file()


@criterion
def default_matches(workspace: Path) -> bool:
    f = workspace / "default.txt"
    return f.is_file() and f.read_text().strip() == EXPECTED_DEFAULT
