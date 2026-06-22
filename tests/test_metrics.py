"""Locks the call-classification and metric logic in mcp_evals.metrics.

Tool-call shapes are hand-written minimal ATIF fragments mirroring real
harness output: claude-code (`Bash`, `mcp__apify__*`), opencode (`bash`,
`apify_*`), codex (`exec_command` with `cmd`, prefix-stripped MCP names).
"""

import json

from mcp_evals.metrics import (
    call_errored,
    classify_call,
    compute_trial_metrics,
    app_for_task,
    failed_criteria,
    sum_subagent_tokens,
)
from mcp_evals.metrics import tests_passed as check_tests_passed


def _call(name, **arguments):
    return {"tool_call_id": "t1", "function_name": name, "arguments": arguments}


class TestClassifyCall:
    def test_cli_connector_across_harnesses(self):
        claude = _call("Bash", command="apify actors info apify/web-scraper")
        opencode = _call("bash", command="apify api GET /v2/acts/x")
        codex = _call("exec_command", cmd="apify actors ls")
        for tc in (claude, opencode, codex):
            assert classify_call(tc, "apify", "cli") == "connector"

    def test_mcp_connector_across_harnesses(self):
        claude = _call("mcp__apify__fetch-actor-details", actor="apify/web-scraper")
        opencode = _call("apify_fetch-actor-details", actor="apify/web-scraper")
        codex = _call("fetch_actor_details", actor="apify/web-scraper")
        for tc in (claude, opencode, codex):
            assert classify_call(tc, "apify", "mcp") == "connector"

    def test_mcpc_connector(self):
        tc = _call("bash", command="mcpc apify tools")
        assert classify_call(tc, "apify", "mcpc") == "connector"

    def test_wrong_connector_is_escape(self):
        cli_in_mcp = _call("bash", command="apify actors ls")
        assert classify_call(cli_in_mcp, "apify", "mcp") == "escape"
        mcp_in_cli = _call("apify_fetch-actor-details")
        assert classify_call(mcp_in_cli, "apify", "cli") == "escape"

    def test_raw_api_is_escape(self):
        tc = _call("Bash", command='curl -s "https://api.apify.com/v2/acts/x"')
        assert classify_call(tc, "apify", "cli") == "escape"
        assert classify_call(tc, "apify", "mcp") == "escape"

    def test_workspace_and_other(self):
        assert classify_call(_call("Write", file_path="/app/x.txt"), "apify", "mcp") == "workspace"
        assert classify_call(_call("read", filePath="/app/x.txt"), "apify", "cli") == "workspace"
        assert classify_call(_call("bash", command="cat /etc/hosts"), "apify", "cli") == "other"

    def test_github_target(self):
        assert classify_call(_call("bash", command="gh pr view 1"), "github", "cli") == "connector"
        assert classify_call(_call("mcp__github__get_pull_request"), "github", "mcp") == "connector"
        curl = _call("bash", command="curl https://api.github.com/repos/x/y/pulls/1")
        assert classify_call(curl, "github", "cli") == "escape"

    def test_unknown_target_or_connector(self):
        tc = _call("bash", command="apify actors ls")
        assert classify_call(tc, None, "cli") == "other"
        # No expected connector -> nothing to escape from.
        assert classify_call(tc, "apify", None) == "other"


class TestCallErrored:
    def test_error_prefix(self):
        assert call_errored("Error: Command actors:get-id not found\n")

    def test_codex_exit_codes(self):
        assert not call_errored("Chunk ID: x Wall time: 0.1 Process exited with code 0 Output: done")
        assert call_errored("Process exited with code 2 Output: boom")

    def test_clean_output(self):
        assert not call_errored("Wrote file successfully.")
        assert not call_errored("# Actor information\n## Web Scraper")


class TestComputeTrialMetrics:
    def _trajectory(self):
        return {
            "steps": [
                {"step_id": 1, "source": "user", "message": "do the task"},
                {
                    "step_id": 2,
                    "source": "agent",
                    "metrics": {"prompt_tokens": 12970, "completion_tokens": 50},
                    "tool_calls": [
                        {"tool_call_id": "a", "function_name": "apify_fetch-actor-details",
                         "arguments": {"actor": "apify/web-scraper"}},
                    ],
                    "observation": {"results": [{"source_call_id": "a", "content": "x" * 500}]},
                },
                {
                    "step_id": 3,
                    "source": "agent",
                    "metrics": {"prompt_tokens": 14000, "completion_tokens": 30},
                    "tool_calls": [
                        {"tool_call_id": "b", "function_name": "bash",
                         "arguments": {"command": "curl https://api.apify.com/v2/acts/x"}},
                        {"tool_call_id": "c", "function_name": "write",
                         "arguments": {"filePath": "/app/actor_id.txt", "content": "id"}},
                    ],
                    "observation": {"results": [
                        {"source_call_id": "b", "content": "Error: blocked"},
                        {"source_call_id": "c", "content": "Wrote file successfully."},
                    ]},
                },
                {"step_id": 4, "source": "agent",
                 "metrics": {"prompt_tokens": 15000, "completion_tokens": 10}},
            ]
        }

    def test_metrics(self):
        metrics, per_call = compute_trial_metrics(self._trajectory(), {"apify": "mcp"})
        assert metrics == {
            "agent_turns": 3,
            "tool_calls_total": 3,
            "connector_calls": 1,
            "off_connector_calls": 1,
            "errored_calls": 1,
            "connector_output_chars": 500,
            "prompt_baseline_tokens": 12970,
        }
        assert [c["kind"] for c in per_call] == ["connector", "escape", "workspace"]
        assert per_call[1]["output_head"] == "Error: blocked"

    def test_call_values(self):
        from mcp_evals.metrics import call_values
        _, per_call = compute_trial_metrics(self._trajectory(), {"apify": "mcp"})
        values = call_values(per_call)
        assert values["escape_call_values"] == ["bash: curl https://api.apify.com/v2/acts/x"]
        assert values["errored_call_values"] == [
            "bash: curl https://api.apify.com/v2/acts/x -> Error: blocked"
        ]

    def test_codex_missing_step_metrics(self):
        traj = {
            "steps": [
                {"step_id": 1, "source": "agent", "metrics": None,
                 "tool_calls": [{"tool_call_id": "a", "function_name": "fetch_actor_details",
                                 "arguments": {}}]},
            ]
        }
        metrics, _ = compute_trial_metrics(traj, {"apify": "mcp"})
        assert metrics["prompt_baseline_tokens"] is None
        assert metrics["connector_calls"] == 1

    def test_empty_trajectory(self):
        metrics, per_call = compute_trial_metrics({}, {"apify": "mcp"})
        assert metrics["tool_calls_total"] == 0
        assert per_call == []


class TestRewardDetails:
    DETAILS = {
        "reward": {
            "score": 0.6667,
            "criteria": [
                {"name": "used_expected_connector", "value": 1.0, "raw": True},
                {"name": "actor_id_file_exists", "value": 1.0, "raw": True},
                {"name": "actor_id_matches", "value": 0.0, "raw": False},
            ],
        }
    }

    def test_tests_passed(self):
        assert check_tests_passed(self.DETAILS) is False
        all_pass = {"reward": {"criteria": [{"name": "x", "value": 1.0, "raw": True}]}}
        assert check_tests_passed(all_pass) is True
        assert check_tests_passed(None) is None
        assert check_tests_passed({"reward": {}}) is None

    def test_failed_criteria(self):
        assert failed_criteria(self.DETAILS) == ["actor_id_matches"]


class TestSumSubagentTokens:
    def _write_subagent(self, path, turns):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as fh:
            for u in turns:
                fh.write(json.dumps({"type": "assistant", "message": {"usage": u}}) + "\n")
            # noise records that must be ignored
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n")

    def test_sums_across_subagent_files(self, tmp_path):
        sub = tmp_path / "agent" / "sessions" / "projects" / "-app" / "sess" / "subagents"
        self._write_subagent(sub / "agent-a.jsonl", [
            {"input_tokens": 3, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 1000, "output_tokens": 50},
            {"input_tokens": 1, "output_tokens": 5},
        ])
        self._write_subagent(sub / "agent-b.jsonl", [
            {"input_tokens": 2, "cache_read_input_tokens": 200, "output_tokens": 20},
        ])
        # 3+100+1000+50 + 1+5 + 2+200+20 == 1381
        assert sum_subagent_tokens(tmp_path) == 1381

    def test_returns_zero_without_sessions_dir(self, tmp_path):
        assert sum_subagent_tokens(tmp_path) == 0

    def test_returns_zero_without_subagents(self, tmp_path):
        (tmp_path / "agent" / "sessions").mkdir(parents=True)
        assert sum_subagent_tokens(tmp_path) == 0

    def test_skips_malformed_lines(self, tmp_path):
        sub = tmp_path / "agent" / "sessions" / "projects" / "-app" / "sess" / "subagents"
        sub.mkdir(parents=True)
        path = sub / "agent-x.jsonl"
        with open(path, "w") as fh:
            fh.write("not json\n")
            fh.write(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 7, "output_tokens": 3}}}) + "\n")
        assert sum_subagent_tokens(tmp_path) == 10


def test_app_for_task():
    assert app_for_task("apify-fetch-actor-id") == "apify"
    assert app_for_task("github-pr-info") == "github"
    assert app_for_task("e2b-smoke") is None
