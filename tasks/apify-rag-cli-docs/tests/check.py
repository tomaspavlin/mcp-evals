import json
import os
from pathlib import Path

from rewardkit import criterion
from rewardkit.criteria._trajectory import collect_tool_calls, load_trajectory

TRAJECTORY_PATH = "/logs/agent/trajectory.json"
import json as _json
CONNECTOR = "apify"
_channels = _json.loads(os.environ.get("MCP_EVALS_CHANNELS_JSON") or "{}")
EXPECTED_CHANNEL = _channels.get(CONNECTOR) or os.environ.get("MCP_EVALS_CHANNEL") or None
# `skill` channel is CLI usage + extra prompt; match like cli.
if EXPECTED_CHANNEL == "skill":
    EXPECTED_CHANNEL = "cli"
RESULT_PATH = "cli_rag.json"

INSTALL_KEYWORDS = ("install", "installation", "setup")
PKG_MGR_KEYWORDS = ("npm", "brew", "yarn", "pnpm")


def _tool_calls() -> list[dict]:
    data = load_trajectory(TRAJECTORY_PATH)
    return collect_tool_calls(data) if data else []


# Channel matching mirrored from src/mcp_evals/metrics.py.
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


def _load_result(workspace: Path) -> dict | None:
    f = workspace / RESULT_PATH
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


@criterion(description=f"agent used expected channel ({EXPECTED_CHANNEL or 'n/a'})")
def used_expected_channel(workspace: Path) -> bool:
    if not EXPECTED_CHANNEL:
        return True
    return any(_matches_channel(tc, EXPECTED_CHANNEL) for tc in _tool_calls())


@criterion
def result_file_exists(workspace: Path) -> bool:
    return (workspace / RESULT_PATH).is_file()


@criterion
def result_valid_json_object(workspace: Path) -> bool:
    return _load_result(workspace) is not None


@criterion
def result_has_required_keys(workspace: Path) -> bool:
    d = _load_result(workspace)
    return d is not None and {"pageCount", "installPreview", "urlsContainingActor"} <= d.keys()


@criterion
def page_count_in_range(workspace: Path) -> bool:
    # maxCrawlPages caps the crawl but the Actor counts pagination/no-content
    # pages toward the cap and may slightly overshoot, so the upper bound is
    # widened past the prompt's "50 or fewer" cost guardrail.
    d = _load_result(workspace) or {}
    pc = d.get("pageCount")
    return isinstance(pc, int) and 3 <= pc <= 60


@criterion
def install_preview_length_in_range(workspace: Path) -> bool:
    d = _load_result(workspace) or {}
    p = d.get("installPreview")
    return isinstance(p, str) and 50 <= len(p) <= 300


@criterion
def install_preview_mentions_install(workspace: Path) -> bool:
    d = _load_result(workspace) or {}
    p = d.get("installPreview", "")
    return isinstance(p, str) and any(k in p.lower() for k in INSTALL_KEYWORDS)


@criterion
def install_preview_mentions_package_manager(workspace: Path) -> bool:
    d = _load_result(workspace) or {}
    p = d.get("installPreview", "")
    return isinstance(p, str) and any(k in p.lower() for k in PKG_MGR_KEYWORDS)


@criterion
def urls_containing_actor_is_int(workspace: Path) -> bool:
    # Programmatic check only verifies the field is a non-negative integer.
    # Correctness of the count (does it match the trajectory's crawled URLs?)
    # is delegated to the judge — see judge.toml.
    d = _load_result(workspace) or {}
    n = d.get("urlsContainingActor")
    return isinstance(n, int) and n >= 0
