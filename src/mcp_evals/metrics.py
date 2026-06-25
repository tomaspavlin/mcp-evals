"""Trajectory-derived metrics shared by dashboards and analysis scripts.

Stdlib-only by design: import this from any app (Streamlit dashboard, notebooks,
scripts) without pulling in harbor or mcp_evals dependencies. Callers do IO and
pass the parsed ATIF trajectory dict.

Connector-matching logic is mirrored (not imported) by the in-container verifier
scripts at tasks/*/tests/check.py; keep both in sync manually.

Harness naming differences this module absorbs:
- claude-code: shell tool `Bash` (arg `command`), MCP `mcp__apify__fetch-actor-details`
- opencode:    shell tool `bash` (arg `command`), MCP `apify_fetch-actor-details`
- codex:       shell tool `exec_command` (arg `cmd`), MCP `fetch_actor_details`
               (server prefix stripped, hyphens normalized to underscores)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Per-app matcher registry. Hardcoded here rather than declared in
# apps/<name>/<connector>/ for now. `mcp_tools` is the allowlist of
# normalized tool names needed for prefix-stripping harnesses (codex); extend
# it when surfacing new tools in the eval.
APPS: dict[str, dict[str, Any]] = {
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
        # codex-style stripped names (no `github_` prefix). Extend when surfacing
        # new GitHub MCP tools in evals - mirrored in tasks/github-*/tests/check.py.
        "mcp_tools": {
            "pull-request-read",
            "pull-request-list",
            "issue-read",
            "issue-list",
            "list-pull-requests",
            "list-issues",
            "get-pull-request",
            "get-issue",
            "list-commits",
            "get-commit",
            "list-releases",
            "get-latest-release",
            "list-branches",
            "list-tags",
            "search-issues",
            "search-pull-requests",
            "search-code",
            "search-repositories",
            "get-file-contents",
            "get-me",
        },
        "cli_prefixes": ("gh ",),
        "api_hosts": ("api.github.com",),
    },
}

MCPC_PREFIXES = ("mcpc ",)
CONNECTORS = ("mcp", "cli", "mcpc")

SHELL_TOOLS = {"bash", "exec_command", "shell", "run_terminal_cmd", "local_shell"}
WORKSPACE_TOOLS = {
    "write", "read", "edit", "multiedit", "notebookedit", "ls", "glob", "grep",
    "apply_patch", "patch", "todowrite", "todoread", "task", "view_image",
}

# Heuristic markers of a failed call, sniffed from observation content
# (ATIF carries no exit code or error flag). Conservative on purpose.
_ERROR_HEAD_PREFIXES = ("error", "traceback (most recent call last)")
_ERROR_SUBSTRINGS = ("command not found", "permission denied")


def parse_run_axes(verifier_env: dict[str, str] | None) -> dict[str, str]:
    """Read the per-app connector map a job wrote to verifier env.

    Prefers MCP_EVALS_CONNECTORS_JSON (multi-app); falls back to
    MCP_EVALS_CONNECTOR + MCP_EVALS_APPS when present. Returns {} when
    neither is set (e.g. old jobs predating these fields).
    """
    env = verifier_env or {}
    raw = env.get("MCP_EVALS_CONNECTORS_JSON")
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except json.JSONDecodeError:
            pass
    connector = env.get("MCP_EVALS_CONNECTOR")
    apps = (env.get("MCP_EVALS_APPS") or "").split(",")
    apps = [c.strip() for c in apps if c.strip()]
    if connector and apps:
        return {c: connector for c in apps}
    return {}


def app_for_task(task_name: str) -> str | None:
    """Derive the primary app from the task-name prefix (apify-*, github-*).

    Multi-app tasks should set `[mcp_evals].apps` in task.toml
    instead of relying on this heuristic - this is a fallback used by the
    dashboard for legacy jobs that didn't write verifier env axes.
    """
    for app in APPS:
        if (task_name or "").startswith(app):
            return app
    return None


def _name(tc: dict) -> str:
    return (tc.get("function_name") or "").lower()


def _command(tc: dict) -> str:
    args = tc.get("arguments") or {}
    return ((args.get("command") or args.get("cmd")) or "").lstrip()


def _normalize_mcp_tool(name: str, app: str) -> str:
    for prefix in APPS[app]["mcp_name_prefixes"]:
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", "-")


def matches_connector(tc: dict, app: str, connector: str) -> bool:
    """True if the tool call interacts with `app` through `connector`."""
    if app not in APPS:
        return False
    # The `skill` connector is conceptually "CLI usage + extra prompt", so a
    # skill cell's calls land on the shell. Match like cli.
    if connector == "skill":
        connector = "cli"
    spec = APPS[app]
    name = _name(tc)
    if connector == "mcp":
        if name.startswith(tuple(p.lower() for p in spec["mcp_name_prefixes"])):
            return True
        return _normalize_mcp_tool(name, app) in spec["mcp_tools"]
    if name not in SHELL_TOOLS:
        return False
    cmd = _command(tc)
    if connector == "cli":
        return cmd.startswith(spec["cli_prefixes"])
    if connector == "mcpc":
        return cmd.startswith(MCPC_PREFIXES)
    return False


# Markers that the command actually issues an HTTP request (rather than just
# containing the api host string as embedded JSON / log text). Conservative
# allowlist; if a real HTTP fetcher is missing here it'll be miscounted as a
# non-escape - prefer that over false positives from heredoc-embedded URLs.
_HTTP_TOOL_MARKERS = (
    "curl", "wget", "httpie", "xh ",
    "urlopen", "urlretrieve", "requests.", "httpx", "aiohttp", "fetch(",
)


def _is_api_escape(tc: dict, app: str) -> bool:
    """Shell call hitting the app's HTTP API directly (curl, python+urllib, etc).

    Requires BOTH an api-host substring AND a recognizable HTTP-issuing tool in
    the command. The HTTP-tool gate filters out heredoc-pasted JSON that
    incidentally contains api.<host>.com URLs (e.g. parsing prior MCP output
    in a local python script).
    """
    if _name(tc) not in SHELL_TOOLS:
        return False
    cmd = _command(tc)
    if not any(host in cmd for host in APPS[app]["api_hosts"]):
        return False
    return any(m in cmd for m in _HTTP_TOOL_MARKERS)


def classify_call(tc: dict, app: str | None, connector: str | None) -> str:
    """Classify one tool call: connector | escape | workspace | other.

    connector   - interaction with the app via the expected connector
    escape    - interaction with the app via any other surface
                (wrong connector, or raw HTTP to the app API)
    workspace - file/editor/bookkeeping tools
    other     - everything else (generic shell, unrelated tools)

    With no expected connector there is nothing to escape from, so app
    interactions fall through to workspace/other.
    """
    if app in APPS and connector:
        if matches_connector(tc, app, connector):
            return "connector"
        for ch in CONNECTORS:
            if ch != connector and matches_connector(tc, app, ch):
                return "escape"
        if _is_api_escape(tc, app):
            return "escape"
    if _name(tc) in WORKSPACE_TOOLS:
        return "workspace"
    return "other"


def classify_call_multi(tc: dict, connectors_by_app: dict[str, str]) -> str:
    """Multi-app classify: a call is `connector` if it matches the expected
    connector for any wired app; `escape` if it touches any wired app
    via another surface; otherwise `workspace`/`other`."""
    if not connectors_by_app:
        return classify_call(tc, None, None)
    for app, connector in connectors_by_app.items():
        if matches_connector(tc, app, connector):
            return "connector"
    for app, connector in connectors_by_app.items():
        for ch in CONNECTORS:
            if ch != connector and matches_connector(tc, app, ch):
                return "escape"
        if _is_api_escape(tc, app):
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
    trajectory: dict,
    connectors_by_app: dict[str, str] | None = None,
    *,
    connector: str | None = None,
    app: str | None = None,
) -> tuple[dict, list[dict]]:
    """Compute per-trial metrics from an ATIF trajectory.

    Pass `connectors_by_app` (e.g. {"apify": "mcp", "github": "mcp"}) for
    multi-app runs. The single-app shorthand `connector=` + `app=`
    is kept for callers that haven't migrated yet.

    Metrics:
      agent_turns            - steps with source == "agent"
      tool_calls_total       - all tool calls of any kind
      connector_calls          - calls matching an expected (app, connector) pair
      off_connector_calls      - escapes: a wired app reached via another surface
      errored_calls          - calls whose observation looks like an error (heuristic)
      connector_output_chars   - total observation content size of connector calls
      prompt_baseline_tokens - prompt_tokens of the first agent step with metrics
                               (None for harnesses without per-step metrics, e.g. codex)
    """
    if connectors_by_app is None:
        if app and connector:
            connectors_by_app = {app: connector}
        else:
            connectors_by_app = {}

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
                "kind": classify_call_multi(tc, connectors_by_app),
                "errored": call_errored(output) if output else False,
                "output_chars": len(output),
                "output_head": output[:160],
            })

    metrics = {
        "agent_turns": agent_turns,
        "tool_calls_total": len(per_call),
        "connector_calls": sum(1 for c in per_call if c["kind"] == "connector"),
        "off_connector_calls": sum(1 for c in per_call if c["kind"] == "escape"),
        "errored_calls": sum(1 for c in per_call if c["errored"]),
        "connector_output_chars": sum(
            c["output_chars"] for c in per_call if c["kind"] == "connector"
        ),
        "prompt_baseline_tokens": prompt_baseline,
    }
    return metrics, per_call


def call_brief(c: dict) -> str:
    """One-line human-readable form of a per_call row: tool name + command/args."""
    args = c.get("arguments") or {}
    cmd = ((args.get("command") or args.get("cmd")) or "").strip()
    detail = cmd or ", ".join(f"{k}={v}" for k, v in list(args.items())[:2])
    return f"{c['name']}: {detail[:100]}" if detail else c["name"]


def call_values(per_call: list[dict]) -> dict[str, list[str]]:
    """The offending calls behind the off_connector_calls / errored_calls counts."""
    return {
        "escape_call_values": [call_brief(c) for c in per_call if c["kind"] == "escape"],
        "errored_call_values": [
            f"{call_brief(c)} -> {c['output_head'][:80]}"
            for c in per_call
            if c["errored"]
        ],
    }


def _all_criteria(reward_details: dict | None) -> list[dict]:
    """Flatten criteria across one-or-many reward blocks (programmatic + judges)."""
    if not reward_details:
        return []
    reward = reward_details.get("reward")
    blocks = reward if isinstance(reward, list) else [reward] if reward else []
    return [c for b in blocks if isinstance(b, dict) for c in (b.get("criteria") or [])]


def tests_passed(reward_details: dict | None) -> bool | None:
    """All verifier criteria passed, from reward-details.json content.

    Returns None when the breakdown is missing/unparseable (caller decides
    how to display unknowns; trials with an exception should be counted as
    not passed by the caller).
    """
    criteria = _all_criteria(reward_details)
    if not criteria:
        return None
    return all(c.get("raw") is True or c.get("value") == 1.0 for c in criteria)


def sum_subagent_tokens(trial_dir: str | Path) -> int:
    """Sum tokens across all claude-code subagent transcripts in a trial.

    Walks `agent/sessions/projects/*/<sessionId>/subagents/agent-*.jsonl` and
    sums `input + cache_creation + cache_read + output` over every assistant
    record's `message.usage`. Returns 0 when no subagents dir exists (codex,
    opencode, and claude-code trials that didn't spawn subagents).
    """
    sessions = Path(trial_dir) / "agent" / "sessions"
    if not sessions.is_dir():
        return 0
    total = 0
    for jsonl in sessions.rglob("subagents/agent-*.jsonl"):
        try:
            with open(jsonl) as fh:
                for line in fh:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if rec.get("type") != "assistant":
                        continue
                    usage = (rec.get("message") or {}).get("usage") or {}
                    total += (
                        (usage.get("input_tokens") or 0)
                        + (usage.get("cache_creation_input_tokens") or 0)
                        + (usage.get("cache_read_input_tokens") or 0)
                        + (usage.get("output_tokens") or 0)
                    )
        except OSError:
            continue
    return total


def failed_criteria(reward_details: dict | None) -> list[str]:
    """Names of criteria that did not pass."""
    return [
        c.get("name", "?")
        for c in _all_criteria(reward_details)
        if not (c.get("raw") is True or c.get("value") == 1.0)
    ]
