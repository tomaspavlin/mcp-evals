import json
import os
from pathlib import Path

from rewardkit import criterion
from rewardkit.criteria._trajectory import collect_tool_calls, load_trajectory

EXPECTED_ACTOR_USERNAME = "apify"
EXPECTED_REPO_LANGUAGE = "Python"
TRAJECTORY_PATH = "/logs/agent/trajectory.json"

_channels = json.loads(os.environ.get("MCP_EVALS_CHANNELS_JSON") or "{}")
_default_channel = os.environ.get("MCP_EVALS_CHANNEL") or None


def _resolve(connector: str) -> str | None:
    ch = _channels.get(connector) or _default_channel
    return "cli" if ch == "skill" else ch


CHANNELS = {"apify": _resolve("apify"), "github": _resolve("github")}


def _tool_calls() -> list[dict]:
    data = load_trajectory(TRAJECTORY_PATH)
    return collect_tool_calls(data) if data else []


CONNECTORS = {
    "apify": {
        "mcp_name_prefixes": ("apify_", "apify-", "mcp__apify__"),
        "mcp_tools": {
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
        },
        "cli_prefix": "apify ",
    },
    "github": {
        "mcp_name_prefixes": ("github_", "github-", "mcp__github__"),
        "mcp_tools": {
            "pull-request-read", "pull-request-list", "issue-read", "issue-list",
            "list-pull-requests", "list-issues", "get-pull-request", "get-issue",
            "list-commits", "get-commit", "list-releases", "get-latest-release",
            "list-branches", "list-tags", "search-issues", "search-pull-requests",
            "search-code", "search-repositories", "get-file-contents", "get-me",
        },
        "cli_prefix": "gh ",
    },
}
SHELL_TOOLS = {"bash", "exec_command", "shell", "run_terminal_cmd", "local_shell"}


def _normalize_mcp_tool(name: str, connector: str) -> str:
    for prefix in CONNECTORS[connector]["mcp_name_prefixes"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", "-")


def _matches(tc: dict, connector: str, channel: str | None) -> bool:
    if not channel:
        return True
    spec = CONNECTORS[connector]
    name = (tc.get("function_name") or "").lower()
    args = tc.get("arguments") or {}
    cmd = ((args.get("command") or args.get("cmd")) or "").lstrip()
    if channel == "mcp":
        return name.startswith(spec["mcp_name_prefixes"]) or _normalize_mcp_tool(name, connector) in spec["mcp_tools"]
    if channel == "cli":
        return name in SHELL_TOOLS and cmd.startswith(spec["cli_prefix"])
    if channel == "mcpc":
        return name in SHELL_TOOLS and cmd.startswith("mcpc ")
    return False


def _log_summary() -> None:
    calls = _tool_calls()
    print(f"[verifier] channels={CHANNELS!r} tool_calls={len(calls)}")
    for i, tc in enumerate(calls):
        name = tc.get("function_name", "")
        args = tc.get("arguments") or {}
        cmd = args.get("command") or args.get("cmd")
        snippet = cmd if cmd else str(args)
        marks = "".join(
            connector[0].upper() if _matches(tc, connector, ch) else " "
            for connector, ch in CHANNELS.items()
        )
        print(f"[verifier] [{marks}] {i:3d} {name}  {str(snippet)[:140]}")


_log_summary()


@criterion(description=f"agent used apify via {CHANNELS['apify'] or 'n/a'}")
def used_apify_channel(workspace: Path) -> bool:
    if not CHANNELS["apify"]:
        return True
    return any(_matches(tc, "apify", CHANNELS["apify"]) for tc in _tool_calls())


@criterion(description=f"agent used github via {CHANNELS['github'] or 'n/a'}")
def used_github_channel(workspace: Path) -> bool:
    if not CHANNELS["github"]:
        return True
    return any(_matches(tc, "github", CHANNELS["github"]) for tc in _tool_calls())


@criterion
def result_file_exists(workspace: Path) -> bool:
    return (workspace / "result.json").is_file()


def _parsed_result(workspace: Path) -> dict:
    p = workspace / "result.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


@criterion
def actor_username_matches(workspace: Path) -> bool:
    return _parsed_result(workspace).get("actor_username") == EXPECTED_ACTOR_USERNAME


@criterion
def repo_language_matches(workspace: Path) -> bool:
    return _parsed_result(workspace).get("repo_language") == EXPECTED_REPO_LANGUAGE
