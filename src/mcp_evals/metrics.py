"""Trajectory-derived metrics shared by dashboards and analysis scripts.

Stdlib-only by design: import this from any app (Streamlit dashboard, notebooks,
scripts) without pulling in harbor or mcp_evals dependencies. Callers do IO and
pass the parsed ATIF trajectory dict.

Channel-matching logic is mirrored (not imported) by the in-container verifier
scripts at tasks/*/tests/check.py; keep both in sync manually.

Harness naming differences this module absorbs:
- claude-code: shell tool `Bash` (arg `command`), MCP `mcp__apify__fetch-actor-details`
- opencode:    shell tool `bash` (arg `command`), MCP `apify_fetch-actor-details`
- codex:       shell tool `exec_command` (arg `cmd`), MCP `fetch_actor_details`
               (server prefix stripped, hyphens normalized to underscores)
"""

from __future__ import annotations

from typing import Any

# Per-target matcher registry. Somewhat hacky: hardcoded here instead of
# declared in integrations/<name>/ because job outputs do not record the
# integration, so there is no reliable join key (see HACK on target_for_task).
# `mcp_tools` is the allowlist of normalized tool names needed for
# prefix-stripping harnesses (codex); extend it when surfacing new tools in
# the eval.
TARGETS: dict[str, dict[str, Any]] = {
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
        "cli_prefixes": ("apify ",),
        "api_hosts": ("api.apify.com",),
    },
    "github": {
        "mcp_name_prefixes": ("github_", "github-", "mcp__github__"),
        "mcp_tools": set(),  # codex-style stripped names unknown yet; extend when needed
        "cli_prefixes": ("gh ",),
        "api_hosts": ("api.github.com",),
    },
}

MCPC_PREFIXES = ("mcpc ",)
CHANNELS = ("mcp", "cli", "mcpc")

SHELL_TOOLS = {"bash", "exec_command", "shell", "run_terminal_cmd", "local_shell"}
WORKSPACE_TOOLS = {
    "write", "read", "edit", "multiedit", "notebookedit", "ls", "glob", "grep",
    "apply_patch", "patch", "todowrite", "todoread", "task", "view_image",
}

# Heuristic markers of a failed call, sniffed from observation content
# (ATIF carries no exit code or error flag). Conservative on purpose.
_ERROR_HEAD_PREFIXES = ("error", "traceback (most recent call last)")
_ERROR_SUBSTRINGS = ("command not found", "permission denied")

# HACK: target inferred from the task-name prefix because trial configs do not
# record it. Breaks for tasks not named <target>-*; record the target in
# verifier env (like EXPECTED_CHANNEL) and read it from trial config instead.
def target_for_task(task_name: str) -> str | None:
    """Derive the eval target from the task-name prefix (apify-*, github-*)."""
    for target in TARGETS:
        if (task_name or "").startswith(target):
            return target
    return None


def _name(tc: dict) -> str:
    return (tc.get("function_name") or "").lower()


def _command(tc: dict) -> str:
    args = tc.get("arguments") or {}
    return ((args.get("command") or args.get("cmd")) or "").lstrip()


def _normalize_mcp_tool(name: str, target: str) -> str:
    for prefix in TARGETS[target]["mcp_name_prefixes"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", "-")


def matches_channel(tc: dict, target: str, channel: str) -> bool:
    """True if the tool call interacts with `target` through `channel`."""
    if target not in TARGETS:
        return False
    spec = TARGETS[target]
    name = _name(tc)
    if channel == "mcp":
        if name.startswith(tuple(p.lower() for p in spec["mcp_name_prefixes"])):
            return True
        return _normalize_mcp_tool(name, target) in spec["mcp_tools"]
    if name not in SHELL_TOOLS:
        return False
    cmd = _command(tc)
    if channel == "cli":
        return cmd.startswith(spec["cli_prefixes"])
    if channel == "mcpc":
        return cmd.startswith(MCPC_PREFIXES)
    return False


def _is_api_escape(tc: dict, target: str) -> bool:
    """Shell call hitting the target's HTTP API directly (curl etc.)."""
    if _name(tc) not in SHELL_TOOLS:
        return False
    cmd = _command(tc)
    return any(host in cmd for host in TARGETS[target]["api_hosts"])


def classify_call(tc: dict, target: str | None, channel: str | None) -> str:
    """Classify one tool call: channel | escape | workspace | other.

    channel   - interaction with the target via the expected channel
    escape    - interaction with the target via any other surface
                (wrong channel, or raw HTTP to the target API)
    workspace - file/editor/bookkeeping tools
    other     - everything else (generic shell, unrelated tools)

    With no expected channel there is nothing to escape from, so target
    interactions fall through to workspace/other.
    """
    if target in TARGETS and channel:
        if matches_channel(tc, target, channel):
            return "channel"
        for ch in CHANNELS:
            if ch != channel and matches_channel(tc, target, ch):
                return "escape"
        if _is_api_escape(tc, target):
            return "escape"
    if _name(tc) in WORKSPACE_TOOLS:
        return "workspace"
    return "other"


def _content_text(content: Any) -> str:
    """Flatten ATIF observation content (str or list of ContentParts) to text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(p.get("text") or "" for p in content if isinstance(p, dict))
    return ""


def call_errored(output: str) -> bool:
    """Heuristic: does this observation content look like a failed call?"""
    head = output.lstrip().lower()[:200]
    if head.startswith(_ERROR_HEAD_PREFIXES):
        return True
    if any(s in head for s in _ERROR_SUBSTRINGS):
        return True
    # codex shell observations: "Process exited with code N"
    marker = "exited with code "
    idx = head.find(marker)
    if idx != -1:
        code = head[idx + len(marker):].split(None, 1)[0].rstrip(".,")
        return code.isdigit() and int(code) != 0
    return False


def compute_trial_metrics(
    trajectory: dict, channel: str | None, target: str | None
) -> tuple[dict, list[dict]]:
    """Compute per-trial metrics from an ATIF trajectory.

    Returns (metrics, per_call_rows). `channel` is the verifier's
    EXPECTED_CHANNEL (mcp | cli | mcpc), `target` e.g. "apify".

    Metrics:
      agent_turns            - steps with source == "agent"
      tool_calls_total       - all tool calls of any kind
      channel_calls          - calls matching the expected channel
      off_channel_calls      - escapes: target reached via another surface
      errored_calls          - calls whose observation looks like an error (heuristic)
      channel_output_chars   - total observation content size of channel calls
      prompt_baseline_tokens - prompt_tokens of the first agent step with metrics
                               (context overhead: system prompt + tool schemas;
                               None for harnesses without per-step metrics, e.g. codex)
    """
    steps = trajectory.get("steps", []) if trajectory else []
    per_call: list[dict] = []
    agent_turns = 0
    prompt_baseline = None

    for step in steps:
        if step.get("source") == "agent":
            agent_turns += 1
            m = step.get("metrics") or {}
            if prompt_baseline is None and m.get("prompt_tokens"):
                prompt_baseline = m["prompt_tokens"]
        outputs = {
            r.get("source_call_id"): _content_text(r.get("content"))
            for r in (step.get("observation") or {}).get("results", [])
        }
        for tc in step.get("tool_calls") or []:
            output = outputs.get(tc.get("tool_call_id"), "")
            per_call.append({
                "step_id": step.get("step_id"),
                "name": tc.get("function_name") or "?",
                "arguments": tc.get("arguments") or {},
                "kind": classify_call(tc, target, channel),
                "errored": call_errored(output) if output else False,
                "output_chars": len(output),
            })

    metrics = {
        "agent_turns": agent_turns,
        "tool_calls_total": len(per_call),
        "channel_calls": sum(1 for c in per_call if c["kind"] == "channel"),
        "off_channel_calls": sum(1 for c in per_call if c["kind"] == "escape"),
        "errored_calls": sum(1 for c in per_call if c["errored"]),
        "channel_output_chars": sum(
            c["output_chars"] for c in per_call if c["kind"] == "channel"
        ),
        "prompt_baseline_tokens": prompt_baseline,
    }
    return metrics, per_call


def tests_passed(reward_details: dict | None) -> bool | None:
    """All verifier criteria passed, from reward-details.json content.

    Returns None when the breakdown is missing/unparseable (caller decides
    how to display unknowns; trials with an exception should be counted as
    not passed by the caller).
    """
    if not reward_details:
        return None
    criteria = (reward_details.get("reward") or {}).get("criteria")
    if not criteria:
        return None
    return all(c.get("raw") is True or c.get("value") == 1.0 for c in criteria)


def failed_criteria(reward_details: dict | None) -> list[str]:
    """Names of criteria that did not pass."""
    if not reward_details:
        return []
    criteria = (reward_details.get("reward") or {}).get("criteria") or []
    return [
        c.get("name", "?")
        for c in criteria
        if not (c.get("raw") is True or c.get("value") == 1.0)
    ]
