# Agent × integration matrix (easy tasks)

Run on 2026-06-15. Tasks: `apify-fetch-actor-id` (apify columns), `github-pr-info` (github columns). One trial per cell, 36 trials total.

Configs: `configs/{apify-fetch-actor-id,github-pr-info}-matrix-{mcp,cli,mcpc,skill}-eval.yaml`.

## Reward matrix

`E` = cell had at least one errored trial. Reward = 0.0 to 1.0 (programmatic + judge averaged).

```
agent                       apify-mcp   apify-cli  apify-mcpc apify-skill  github-mcp  github-cli
------------------------------------------------------------------------------------------------
opencode  ds-v4-flash           1.000       1.000 E     0.000       1.000       1.000       1.000
opencode  ds-v4-pro             1.000       1.000 E     0.000       1.000       1.000       1.000
claude    haiku-4.5             1.000       1.000 E     1.000       0.667       1.000       1.000
claude    sonnet-4.6            0.667       1.000       1.000       1.000       0.500       1.000
codex     gpt-5.4-mini          0.000       1.000       1.000       1.000       0.000       1.000
codex     gpt-5.4               0.000       1.000       1.000       1.000       0.000       1.000
```

Per integration:

```
apify-cli      1.000  (perfect across all 6 agents)
github-cli     1.000  (perfect across all 6 agents)
apify-skill    0.944  (one partial: haiku)
apify-mcpc     0.667  (3 errors: opencode x2, haiku)
apify-mcp      0.611  (codex 0.0 x2, sonnet 0.667)
github-mcp     0.583  (codex 0.0 x2, sonnet 0.5)
```

Per agent (averaged across integrations):

```
claude    haiku-4.5      0.944
claude    sonnet-4.6     0.861
opencode  ds-v4-flash    0.833
opencode  ds-v4-pro      0.833
codex     gpt-5.4-mini   0.667
codex     gpt-5.4        0.667
```

## Failing trials to fix

Grouped by root cause. Check off as fixed.

### Group A: codex on MCP integrations - FIXED (4 cells, was 0.000, now 1.000)

Root cause was three stacked bugs, each masking the next once the previous was fixed.

Bug 1: provider routing. Codex CLI 0.139 uses OpenAI's Responses API over WebSocket. With `OPENAI_BASE_URL=https://openrouter.ai/api/v1`, codex hits `wss://openrouter.ai/api/v1/responses` which 404s. OpenRouter does not implement the Responses API at that path. Codex retries 5x then falls into a degraded mode where MCP tools are not registered with the model; the model emits one commentary message and codex fires `task_complete` with zero tool calls. Fix: new monkey-patch `src/mcp_evals/_patches/codex_wire_api.py` writes a `[model_providers.openrouter]` block to `$CODEX_HOME/config.toml` with `wire_api = "responses"` + `disable_response_storage = true`, and selects it via top-level `model_provider = "openrouter"`. Subtlety: the top-level keys MUST come before any `[section]` header, otherwise TOML scoping makes them sub-keys of the provider table and codex silently keeps using its default `openai` provider. `wire_api = "chat"` is no longer accepted by codex 0.139 (see codex issue 7782).

Bug 2: token forwarding. The existing `src/mcp_evals/_patches/codex_mcp_env.py` allowlist only had `apify`. When codex spawned `github-mcp-proxy` for the github integration, no `GITHUB_TOKEN` was forwarded; the proxy's `${GITHUB_TOKEN:?...}` guard killed it immediately, codex saw zero tools, model gave commentary only. Fix: added `"github": ["GITHUB_TOKEN"]` to `MCP_SERVER_ENV`.

Bug 3: verifier channel matching. Codex emits MCP tool calls as their bare tool name (`pull_request_read`), no `github_` prefix. The github task `check.py` files only matched `("github_", "github-", "mcp__github__")` prefixes, so codex's tool calls were counted as non-MCP. claude-code and opencode preserve a prefix and passed; codex didn't. Fix: ported the apify-task pattern - `GITHUB_MCP_TOOLS` allowlist + `_normalize_mcp_tool` helper - to `tasks/github-pr-info/tests/check.py` and to all 16 other `tasks/github-*/tests/check.py` files (batch-applied via `/tmp/claude/apply_gh_mcp_allowlist.py`).

- [x] `codex + gpt-5.4-mini` x `apify-mcp` (1.000)
- [x] `codex + gpt-5.4` x `apify-mcp` (1.000)
- [x] `codex + gpt-5.4-mini` x `github-mcp` (1.000)
- [x] `codex + gpt-5.4` x `github-mcp` (1.000)

### Group B: apify-mcpc — e2b template collision (3 cells, whole column invalid)

Root cause (diagnosed 2026-06-15, NOT integration-side): all 4 apify matrix configs ran concurrently and materialize into the **same** `tasks/apify-fetch-actor-id/environment/` (shared, task-keyed). The mcpc trials hashed+built the **apify-cli** image (`apify-fetch-actor-id__d0745b9e`) - `mcpc` was never installed, every `mcpc …` returned exit 127, and agents fell back to `curl`. The verifier's `cmd.startswith("mcpc ")` check counts the failed attempt as success, so the 1.0 mcpc cells (sonnet, both codex) are **false passes** - the whole apify-mcpc column is noise. opencode's `BuildException` is a second race (concurrent build of the same uncached alias; no build lock in the e2b backend). haiku's `NonZeroAgentExitCodeError` is the same wrong-image: it flailed 20 turns looking for `mcpc`, hit `--max-turns 20` → claude exits 1 (still wrote the right actor_id first → reward 1.0).

Full write-up + fix plan: `docs/todo.md` § "E2B template collision across concurrent same-task integration jobs".

Stopgap (this run): re-run the apify integration configs **serially**, one at a time, not concurrently. That makes each integration build its own correct image.

- [ ] `opencode + ds-v4-flash` x `apify-mcpc` (rerun serial)
- [ ] `opencode + ds-v4-pro` x `apify-mcpc` (rerun serial)
- [ ] `claude-code + haiku-4.5` x `apify-mcpc` (rerun serial)
- [ ] re-verify the whole apify-mcpc column once mcpc actually runs (current 1.0 cells are false passes)

### Group C: apify-skill partial on haiku (1 cell, reward 0.667) - NOT A BUG, real result

Root cause: haiku ignored the skill and used `WebFetch` against `https://api.apify.com/v2/acts/apify~web-scraper` directly, then `Write` to `/app/actor_id.txt`. Two tool calls, zero `apify` CLI invocations. `actor_id_file_exists` and `actor_id_matches` passed; `used_expected_channel (cli)` failed.

Every other agent on this integration loaded the skill and went through the CLI. Haiku didn't. The integration's `instruction.md` says the skill is "available", not required, and haiku took the shortcut. This is the eval working as intended - it's measuring whether the skill drives CLI usage, and haiku's score reflects that it doesn't reliably here. No fix.

- [x] `claude-code + haiku-4.5` x `apify-skill` (0.667 reward) - real result, kept as-is

### Group D: claude sonnet partial on MCP (2 cells) - NOT A BUG, real result

Root cause: sonnet delegates the work to claude-code's built-in `Agent` (subagent) tool, and **claude-code subagents are spawned without the parent's MCP servers**. The subagent therefore has no MCP available and falls back to shell:
- `apify-mcp` x sonnet (`apify-fetch-actor-id__C4cL9E3`): parent runs `Agent` → subagent tries `apify` CLI (not installed) → falls back to `WebFetch https://api.apify.com/v2/acts/apify~web-scraper` → parent writes file. `actor_id_*` pass, `used_expected_channel(mcp)` fails → 0.667.
- `github-mcp` x sonnet (`github-pr-info__3Am3r5E`): parent `Agent` → two nested `Agent` calls → leaf subagent runs `Bash: gh pr view 50782 ...` (gh ships in the github task env). Sonnet's prompts to the subagents literally said "Do NOT use gh CLI - use only GitHub MCP tools" but the subagent had no MCP to use. Programmatic `used_expected_channel(mcp)=0`; judge gave a false PASS reasoning "successfully executed a GitHub MCP tool call" (contradicted by the trajectory) → 0.500.

Zero MCP calls in either trial. Verifier is correct. This is sonnet's delegation habit interacting with claude-code's subagent-MCP-isolation - a real behavioral pattern worth keeping in the data.

Visibility caveat: subagent transcripts live at `<trial>/agent/sessions/projects/-app/<sid>/subagents/agent-*.jsonl`. Neither `harbor view jobs` nor `apps/dashboard/` surfaces them; the claude-code adapter (`harbor/agents/installed/claude_code.py:182`) excludes subagent paths when building ATIF, so the parent `trajectory.json` shows only the opaque `Agent` tool call. See `docs/todo.md` § "Subagent trajectories invisible to viewer + verifier".

- [x] `claude-code + sonnet-4.6` x `apify-mcp` (0.667 reward) - real result, kept as-is
- [x] `claude-code + sonnet-4.6` x `github-mcp` (0.500 reward) - real result, kept as-is

## Observations worth keeping

- CLI integration is universally clean. Every agent x model combination scored 1.000 on `apify-cli` and `github-cli`.
- MCP integration is fine for opencode and claude-code, broken for codex.
- Easy tasks ceiling out at 1.000 for most cells. For capability ranking the hard task is needed (after codex routing and mcpc build are fixed).
- Previous hard-task run (`apify-lead-gen-coffee` + `github-weekly-catchup`, 2026-06-14) hit OpenRouter daily credit limit on claude-sonnet. Credits replenished before this run.
