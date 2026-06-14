import os
from pathlib import Path

from rewardkit import criterion
from rewardkit.criteria._trajectory import collect_tool_calls, load_trajectory

TRAJECTORY_PATH = "/logs/agent/trajectory.json"

EXPECTED_CHANNEL = os.environ.get("EXPECTED_CHANNEL") or None


def _tool_calls() -> list[dict]:
    data = load_trajectory(TRAJECTORY_PATH)
    return collect_tool_calls(data) if data else []


# Channel matching mirrored from src/mcp_evals/metrics.py (cannot import the
# package inside the verifier container); keep both in sync manually.
#
# Apify MCP tool allowlist for harnesses that strip the server prefix from
# tool names (codex: "fetch_actor_details"). Claude-code preserves a
# "mcp__apify__" prefix, opencode an "apify_" prefix; both are caught by the
# prefix check directly, this list only needs to cover the prefix-strippers.
# Extend when surfacing new apify tools in the eval.
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
        return name.startswith(MCP_NAME_PREFIXES) or _normalize_mcp_tool(name) in APIFY_MCP_TOOLS
    if channel == "cli":
        return name in SHELL_TOOLS and cmd.startswith("apify ")
    if channel == "mcpc":
        return name in SHELL_TOOLS and cmd.startswith("mcpc ")
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


@criterion
def answer_file_exists(workspace: Path) -> bool:
    return (workspace / "answer.md").is_file()
