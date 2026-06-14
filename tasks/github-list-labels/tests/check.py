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
# Shell tool names per harness: opencode "bash", claude-code "Bash" (lowercased
# before comparison), codex "exec_command" (command in the "cmd" argument).
MCP_NAME_PREFIXES = ("github_", "github-", "mcp__github__")
SHELL_TOOLS = {"bash", "exec_command", "shell", "run_terminal_cmd", "local_shell"}


def _matches_channel(tc: dict, channel: str) -> bool:
    name = (tc.get("function_name") or "").lower()
    args = tc.get("arguments") or {}
    cmd = ((args.get("command") or args.get("cmd")) or "").lstrip()
    if channel == "mcp":
        return name.startswith(MCP_NAME_PREFIXES)
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
