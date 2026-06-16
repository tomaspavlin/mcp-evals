import json
import os
import re
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
LEADS_PATH = "leads.json"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


def _tool_calls() -> list[dict]:
    data = load_trajectory(TRAJECTORY_PATH)
    return collect_tool_calls(data) if data else []


# Channel matching mirrored from src/mcp_evals/metrics.py (cannot import the
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


def _load_leads(workspace: Path) -> list[dict] | None:
    f = workspace / LEADS_PATH
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text())
    except Exception:
        return None
    return data if isinstance(data, list) else None


@criterion(description=f"agent used expected channel ({EXPECTED_CHANNEL or 'n/a'})")
def used_expected_channel(workspace: Path) -> bool:
    if not EXPECTED_CHANNEL:
        return True
    return any(_matches_channel(tc, EXPECTED_CHANNEL) for tc in _tool_calls())


@criterion
def leads_file_exists(workspace: Path) -> bool:
    return (workspace / LEADS_PATH).is_file()


@criterion
def leads_valid_json_array(workspace: Path) -> bool:
    return _load_leads(workspace) is not None


@criterion
def leads_has_three_entries(workspace: Path) -> bool:
    leads = _load_leads(workspace)
    return leads is not None and len(leads) == 3


@criterion
def leads_have_required_keys(workspace: Path) -> bool:
    leads = _load_leads(workspace)
    if not leads:
        return False
    return all(isinstance(e, dict) and {"name", "address", "website", "email"} <= e.keys() for e in leads)


@criterion
def leads_addresses_in_portland(workspace: Path) -> bool:
    leads = _load_leads(workspace)
    if not leads:
        return False
    return all(isinstance(e.get("address"), str) and "portland" in e["address"].lower() for e in leads)


@criterion
def leads_have_websites(workspace: Path) -> bool:
    leads = _load_leads(workspace)
    if not leads:
        return False
    n_with_site = sum(1 for e in leads if isinstance(e.get("website"), str) and e["website"].strip().startswith(("http://", "https://")))
    return n_with_site >= 2


@criterion
def emails_are_well_formed(workspace: Path) -> bool:
    leads = _load_leads(workspace)
    if not leads:
        return False
    for e in leads:
        v = e.get("email", "")
        if v and not EMAIL_RE.match(v.strip()):
            return False
    return True
