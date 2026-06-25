import json
import os
from pathlib import Path

from rewardkit import criterion
from rewardkit.criteria._trajectory import collect_tool_calls, load_trajectory

EXPECTED = {
    "actor_id": "shu8hvrXbJbY3Eb9W",
    "crawlee_default_branch": "master",
    "crawlee_license": "Apache-2.0",
    "crawlee_python_default_branch": "master",
    "crawlee_python_license": "Apache-2.0",
    "more_topics_repo": "tied",
}
TRAJECTORY_PATH = "/logs/agent/trajectory.json"

_connectors = json.loads(os.environ.get("MCP_EVALS_CONNECTORS_JSON") or "{}")
_default_connector = os.environ.get("MCP_EVALS_CONNECTOR") or None


def _resolve(app: str) -> str | None:
    ch = _connectors.get(app) or _default_connector
    return "cli" if ch in ("skill", "cli+skill") else ch


CONNECTORS = {"apify": _resolve("apify"), "github": _resolve("github")}


def _tool_calls() -> list[dict]:
    data = load_trajectory(TRAJECTORY_PATH)
    return collect_tool_calls(data) if data else []


APPS = {
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


def _normalize_mcp_tool(name: str, app: str) -> str:
    for prefix in APPS[app]["mcp_name_prefixes"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", "-")


def _matches(tc: dict, app: str, connector: str | None) -> bool:
    if not connector:
        return True
    spec = APPS[app]
    name = (tc.get("function_name") or "").lower()
    args = tc.get("arguments") or {}
    cmd = ((args.get("command") or args.get("cmd")) or "").lstrip()
    if connector == "mcp":
        return name.startswith(spec["mcp_name_prefixes"]) or _normalize_mcp_tool(name, app) in spec["mcp_tools"]
    if connector == "cli":
        return name in SHELL_TOOLS and cmd.startswith(spec["cli_prefix"])
    if connector == "mcpc":
        return name in SHELL_TOOLS and cmd.startswith("mcpc ")
    return False


def _log_summary() -> None:
    calls = _tool_calls()
    print(f"[verifier] connectors={CONNECTORS!r} tool_calls={len(calls)}")
    for i, tc in enumerate(calls):
        name = tc.get("function_name", "")
        args = tc.get("arguments") or {}
        cmd = args.get("command") or args.get("cmd")
        snippet = cmd if cmd else str(args)
        marks = "".join(
            app[0].upper() if _matches(tc, app, ch) else " "
            for app, ch in CONNECTORS.items()
        )
        print(f"[verifier] [{marks}] {i:3d} {name}  {str(snippet)[:140]}")


_log_summary()


@criterion(description=f"agent used apify via {CONNECTORS['apify'] or 'n/a'}")
def used_apify_connector(workspace: Path) -> bool:
    if not CONNECTORS["apify"]:
        return True
    return any(_matches(tc, "apify", CONNECTORS["apify"]) for tc in _tool_calls())


@criterion(description=f"agent used github via {CONNECTORS['github'] or 'n/a'}")
def used_github_connector(workspace: Path) -> bool:
    if not CONNECTORS["github"]:
        return True
    return any(_matches(tc, "github", CONNECTORS["github"]) for tc in _tool_calls())


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
def actor_id_matches(workspace: Path) -> bool:
    return _parsed_result(workspace).get("actor_id") == EXPECTED["actor_id"]


@criterion
def crawlee_default_branch_matches(workspace: Path) -> bool:
    return _parsed_result(workspace).get("crawlee_default_branch") == EXPECTED["crawlee_default_branch"]


@criterion
def crawlee_license_matches(workspace: Path) -> bool:
    return _parsed_result(workspace).get("crawlee_license") == EXPECTED["crawlee_license"]


@criterion
def crawlee_python_default_branch_matches(workspace: Path) -> bool:
    return _parsed_result(workspace).get("crawlee_python_default_branch") == EXPECTED["crawlee_python_default_branch"]


@criterion
def crawlee_python_license_matches(workspace: Path) -> bool:
    return _parsed_result(workspace).get("crawlee_python_license") == EXPECTED["crawlee_python_license"]


@criterion
def more_topics_repo_matches(workspace: Path) -> bool:
    return _parsed_result(workspace).get("more_topics_repo") == EXPECTED["more_topics_repo"]
