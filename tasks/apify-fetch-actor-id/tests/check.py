import os
from pathlib import Path

from rewardkit import criterion
from rewardkit.criteria._trajectory import collect_tool_calls, load_trajectory

EXPECTED_ID = "moJRLRc85AitArpNN"
TRAJECTORY_PATH = "/logs/agent/trajectory.json"

EXPECTED_CHANNEL = os.environ.get("EXPECTED_CHANNEL") or None


def _tool_calls() -> list[dict]:
    data = load_trajectory(TRAJECTORY_PATH)
    return collect_tool_calls(data) if data else []


# Apify MCP tool allowlist for harnesses that strip the server prefix from
# tool names (codex: "fetch_actor_details"). Claude-code/opencode preserve
# the prefix ("apify_fetch-actor-details") and are caught by the apify_
# prefix check directly; this list only needs to cover the prefix-strippers.
# Extend when surfacing new apify tools in the eval.
APIFY_MCP_TOOLS = {
    "fetch-actor-details",
    "search-actors",
    "call-actor",
    "add-actor",
    "fetch-apify-docs",
    "search-apify-docs",
}


def _normalize_mcp_tool(name: str) -> str:
    for prefix in ("apify_", "apify-"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", "-")


def _matches_channel(tc: dict, channel: str) -> bool:
    name = tc.get("function_name") or ""
    cmd = ((tc.get("arguments") or {}).get("command") or "").lstrip()
    if channel == "mcp":
        return name.startswith("apify_") or _normalize_mcp_tool(name) in APIFY_MCP_TOOLS
    if channel == "cli":
        return name == "bash" and cmd.startswith("apify ")
    if channel == "mcpc":
        return name == "bash" and cmd.startswith("mcpc ")
    return False


def _log_summary() -> None:
    calls = _tool_calls()
    print(f"[verifier] expected_channel={EXPECTED_CHANNEL!r} tool_calls={len(calls)}")
    for i, tc in enumerate(calls):
        name = tc.get("function_name", "")
        args = tc.get("arguments") or {}
        cmd = args.get("command")
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
def actor_id_file_exists(workspace: Path) -> bool:
    return (workspace / "actor_id.txt").is_file()


@criterion
def actor_id_matches(workspace: Path) -> bool:
    f = workspace / "actor_id.txt"
    return f.is_file() and f.read_text().strip() == EXPECTED_ID
