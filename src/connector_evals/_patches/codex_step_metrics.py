"""Monkey-patch for Harbor's codex agent: attach per-turn token counts to
individual agent steps in the ATIF trajectory.

# Problem

Harbor's codex adapter reads Codex CLI session JSONL and emits an ATIF
trajectory whose `final_metrics` totals are populated but whose individual
`steps[i].metrics` fields are all `None`. Analysis code that expects per-step
token counts (e.g. cost-per-tool-call breakdowns, per-message trajectory
plots) can't work with codex traces, unlike claude-code traces which carry
`metrics` on every agent step.

# Available data

Codex CLI emits an `event_msg` / `token_count` event at the end of every
model turn. The `payload.info.last_token_usage` field carries the input,
cached input, output, and reasoning-output tokens for just that turn.
Summed across turns, `last_token_usage.input_tokens` equals
`final_metrics.total_prompt_tokens`. The upstream normalization drops these
events (`codex.py:397-401`), losing per-step attribution.

# Fix

Attach each `token_count` event's `last_token_usage` to the last agent step
of that turn. This preserves the sum invariant
    sum(step.metrics.prompt_tokens) == final_metrics.total_prompt_tokens
which matches claude-code convention.

Turn boundaries and their "last agent step" are found by walking the raw
JSONL in the same order as Harbor's normalizer, tracking how many
normalized events have been emitted and remembering the index of the most
recent agent-source emission. When a `token_count` event fires, that index
is the target step for its usage.

TODO: remove when upstream harbor attaches per-step metrics natively.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harbor.agents.installed.codex import Codex
from harbor.models.trajectories.metrics import Metrics
from harbor.models.trajectories.trajectory import Trajectory

_prev_convert_events_to_trajectory = Codex._convert_events_to_trajectory


def _turn_targets(raw_events: list[dict[str, Any]]) -> list[tuple[int, dict[str, Any]]]:
    """Walk the raw session events in Harbor's normalization order and pair
    each `token_count` event with the ATIF step index of the last agent
    emission that came before it.

    Returns a list of `(step_index, last_token_usage)` tuples. `step_index`
    is 0-based into `trajectory.steps`.

    Mirrors the emission logic in `Codex._convert_events_to_trajectory`:
      - `response_item` / `message`: emits one step immediately.
      - `response_item` / `web_search_call`: emits one step immediately.
      - `response_item` / `function_call` and `custom_tool_call`: pending,
        no emission yet.
      - `response_item` / `function_call_output` and `custom_tool_call_output`:
        pops the pending call (if any) and emits one merged step now.
        If no pending call was found, still emits one step (the "orphan"
        fallback in the upstream code).
      - `response_item` / `reasoning`: no emission (stashed as
        `pending_reasoning`).
    """
    targets: list[tuple[int, dict[str, Any]]] = []
    emitted = 0
    last_agent_idx: int | None = None
    pending_calls: dict[str, bool] = {}

    for event in raw_events:
        etype = event.get("type")
        payload = event.get("payload") or {}

        if etype == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            last_usage = info.get("last_token_usage")
            if isinstance(last_usage, dict) and last_agent_idx is not None:
                targets.append((last_agent_idx, last_usage))
            continue

        if etype != "response_item":
            continue

        pt = payload.get("type")
        if pt == "reasoning":
            continue

        if pt == "message":
            role = payload.get("role", "user")
            if role == "assistant":
                last_agent_idx = emitted
            emitted += 1
            continue

        if pt == "web_search_call":
            last_agent_idx = emitted
            emitted += 1
            continue

        if pt in {"function_call", "custom_tool_call"}:
            call_id = payload.get("call_id")
            if call_id:
                pending_calls[call_id] = True
            continue

        if pt in {"function_call_output", "custom_tool_call_output"}:
            call_id = payload.get("call_id")
            if call_id:
                pending_calls.pop(call_id, None)
            last_agent_idx = emitted
            emitted += 1
            continue

    return targets


def _convert_events_to_trajectory(
    self: Codex, session_dir: Path
) -> Trajectory | None:
    trajectory = _prev_convert_events_to_trajectory(self, session_dir)
    if trajectory is None or not trajectory.steps:
        return trajectory

    session_files = list(session_dir.glob("*.jsonl"))
    if not session_files:
        return trajectory

    raw_events: list[dict[str, Any]] = []
    with open(session_files[0], "r") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw_events.append(json.loads(stripped))
            except json.JSONDecodeError:
                continue

    targets = _turn_targets(raw_events)
    n_steps = len(trajectory.steps)

    for step_idx, last_usage in targets:
        if step_idx >= n_steps:
            continue
        step = trajectory.steps[step_idx]
        if step.source != "agent" or step.metrics is not None:
            continue

        extra: dict[str, Any] = {}
        reasoning = last_usage.get("reasoning_output_tokens")
        if reasoning is not None:
            extra["reasoning_output_tokens"] = reasoning
        total = last_usage.get("total_tokens")
        if total is not None:
            extra["total_tokens"] = total

        step.metrics = Metrics(
            prompt_tokens=last_usage.get("input_tokens"),
            completion_tokens=last_usage.get("output_tokens"),
            cached_tokens=last_usage.get("cached_input_tokens"),
            extra=extra or None,
        )

    return trajectory


Codex._convert_events_to_trajectory = _convert_events_to_trajectory
