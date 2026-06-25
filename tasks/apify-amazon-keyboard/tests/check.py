import json
import os
import re
from pathlib import Path

from rewardkit import criterion
from rewardkit.criteria._trajectory import collect_tool_calls, load_trajectory

TRAJECTORY_PATH = "/logs/agent/trajectory.json"
import json as _json
APP = "apify"
_connectors = _json.loads(os.environ.get("MCP_EVALS_CONNECTORS_JSON") or "{}")
EXPECTED_CONNECTOR = _connectors.get(APP) or os.environ.get("MCP_EVALS_CONNECTOR") or None
# `skill` connector is CLI usage + extra prompt; match like cli.
if EXPECTED_CONNECTOR in ("skill", "cli+skill"):
    EXPECTED_CONNECTOR = "cli"
RESULT_PATH = "keyboard.json"
ASIN_RE = re.compile(r"^B0[A-Z0-9]{8}$")

# Stable set of mainstream mechanical-keyboard brands sold on Amazon under $100.
# Used for soft identity verification — the top-reviewed wired mechanical
# keyboard under $100 has historically been from this set. Drift-tolerant.
KNOWN_BRANDS = {
    "logitech", "razer", "redragon", "keychron", "corsair", "hyperx",
    "steelseries", "velocifire", "rk royal kludge", "rk", "akko",
    "cooler master", "havit", "g.skill", "drevo", "tecware", "eagletec",
    "magegee", "qisan", "ducky", "varmilo", "leopold", "filco", "epomaker",
    "perixx", "topre", "fnatic", "tecknet", "gigaware", "vissles",
}


def _tool_calls() -> list[dict]:
    data = load_trajectory(TRAJECTORY_PATH)
    return collect_tool_calls(data) if data else []


# Connector matching mirrored from src/mcp_evals/metrics.py.
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


def _load_result(workspace: Path) -> dict | None:
    f = workspace / RESULT_PATH
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text())
    except Exception:
        return None
    return data if isinstance(data, dict) else None


@criterion(description=f"agent used expected connector ({EXPECTED_CONNECTOR or 'n/a'})")
def used_expected_connector(workspace: Path) -> bool:
    if not EXPECTED_CONNECTOR:
        return True
    return any(_matches_connector(tc, EXPECTED_CONNECTOR) for tc in _tool_calls())


@criterion
def result_file_exists(workspace: Path) -> bool:
    return (workspace / RESULT_PATH).is_file()


@criterion
def result_valid_json_object(workspace: Path) -> bool:
    return _load_result(workspace) is not None


@criterion
def result_has_required_keys(workspace: Path) -> bool:
    d = _load_result(workspace)
    return d is not None and {"asin", "brand", "price", "rating", "reviewCount"} <= d.keys()


@criterion
def asin_format_valid(workspace: Path) -> bool:
    d = _load_result(workspace) or {}
    asin = d.get("asin")
    return isinstance(asin, str) and bool(ASIN_RE.match(asin))


@criterion
def price_under_100(workspace: Path) -> bool:
    d = _load_result(workspace) or {}
    p = d.get("price")
    try:
        return isinstance(p, (int, float)) and 0 < float(p) < 100
    except Exception:
        return False


@criterion
def rating_at_least_44(workspace: Path) -> bool:
    d = _load_result(workspace) or {}
    r = d.get("rating")
    try:
        return isinstance(r, (int, float)) and float(r) >= 4.4
    except Exception:
        return False


@criterion
def review_count_at_least_1000(workspace: Path) -> bool:
    d = _load_result(workspace) or {}
    rc = d.get("reviewCount")
    try:
        return isinstance(rc, int) and rc >= 1000
    except Exception:
        return False


@criterion
def brand_in_known_set(workspace: Path) -> bool:
    d = _load_result(workspace) or {}
    brand = d.get("brand")
    if not isinstance(brand, str):
        return False
    return brand.strip().lower() in KNOWN_BRANDS
