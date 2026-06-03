# Harbor: Overview

## What it is

Harbor is "a framework for evaluating and optimizing agents and models in container environments," built by the same team that created Terminal-Bench (tbench.ai). Harbor is the official harness for Terminal-Bench 2.0. It evolved out of Terminal-Bench into a general-purpose harness for arbitrary agentic evals + RL rollouts.

- Website: https://www.harborframework.com/
- Docs: https://www.harborframework.com/docs
- GitHub: https://github.com/harbor-framework/harbor
- Cookbook (realistic examples): https://github.com/harbor-framework/harbor-cookbook
- Terminal-Bench source: https://github.com/harbor-framework/terminal-bench

## Language and distribution

**Harbor is Python (3.12+) and distributed on PyPI.** There is no JS/TS port and no language-agnostic API for *driving* the harness — the CLI and the eval engine are Python. (Implications for our project: see `architecture-decisions.md`.)

Install:
```bash
uv tool install harbor   # preferred
# or
pip install harbor
```

Stack notes:
- Typer-based CLI (`harbor` binary)
- Pydantic v2 models for all config
- asyncio throughout (`asyncio.TaskGroup`)
- LiteLLM under the hood for LLM provider abstraction
- Docker (local) by default, plus cloud sandbox providers: Daytona, E2B, Modal, Runloop, Apple Container, GKE, Novita
- Docs site is Next.js/Fumadocs (TS), but that's only the marketing/docs site, not the runtime

tbench/Terminal-Bench is itself a Python package (`tb` CLI) and uses Harbor as the harness — they're sibling repos in the same org. Terminal-Bench is *consumed by* Harbor as a dataset (`harbor run --dataset terminal-bench@2.0 ...`), it doesn't replace it.

## Core abstractions

Source of truth: [Harbor docs > Task Structure](https://www.harborframework.com/docs/tasks) and [`src/harbor/` in the repo](https://github.com/harbor-framework/harbor/tree/main/src/harbor).

| Concept | What it is | Where it lives |
|---|---|---|
| **Task** | A directory with `task.toml`, `instruction.md`, `environment/`, `tests/`, optional `solution/`. The unit of eval. Declarative config + scripts. | `src/harbor/models/task/`, examples in `examples/tasks/` |
| **Agent** | A class extending `BaseAgent` that knows how to set up and run a CLI agent (claude-code, codex, opencode, openhands, aider, goose, ...) inside an environment. Implements `setup()` + `run(instruction, environment, context)`. | `src/harbor/agents/installed/*.py` |
| **Environment** | Container runtime — `BaseEnvironment` impls for `docker` (local, supports Docker Compose), `daytona`, `e2b`, `modal`, `runloop`, `gke`, `apple_container`, `novita`. Single-Dockerfile vs Compose support varies by provider. | `src/harbor/environments/` |
| **Verifier** | The `tests/test.sh` script that runs inside the container and writes a reward to `/logs/verifier/reward.txt` (single float) or `reward.json` (multi-metric). Free-form: pytest, shell asserts, LLM-judge, whatever. Can run "shared" with the agent container or "separate" in a locked-down grading image. | `src/harbor/verifier/`, `tests/test.sh` in each task |
| **Trial** | One execution: a (task, agent, model) tuple. | `src/harbor/models/trial/` |
| **Job** | A collection of trials, e.g. N agents × M tasks × K attempts. Run in parallel via `--n-concurrent`. | `src/harbor/models/job/`, `examples/configs/*.yaml` |
| **Dataset** | A registered collection of tasks (e.g. `terminal-bench@2.0`, `swe-bench`). Listed via `harbor datasets list`. | `src/harbor/dataset/`, `registry.json` |
| **Adapter** | Converter from an external benchmark format (SWE-Bench, Aider Polyglot, GAIA, etc.) into Harbor's task format. 50+ exist. | `adapters/` |
| **Trace / Trajectory** | Agent rollouts in ATIF (Agent Trajectory Interchange Format). | `src/harbor/models/trajectories/` |
| **Metric / Rewardkit** | Reward computation. Single reward (0/1 float) is built-in. Multi-criteria, score aggregation, LLM-judging via [Rewardkit](https://www.harborframework.com/docs/rewardkit). | `src/harbor/metrics/`, `packages/rewardkit/`, `examples/metrics/` |

How they compose at runtime (simplified, from `src/harbor/agents/base.py`):

```python
async def run_trial():
    await environment.start(force_build=False)
    await agent.setup(environment)
    await agent.run(instruction, environment, context)
    result = await verifier.verify()   # reads /logs/verifier/reward.{txt,json}
    await environment.stop(delete=True)
```

## Harness / LLM integration

Each "agent" in Harbor wraps a real CLI agent — Harbor installs it into the container, configures it (API keys, MCP servers, skills), feeds it the instruction, and waits.

Built-in installed agents (relevant to us):

- `claude-code` — Anthropic Claude Code CLI
- `codex` — OpenAI Codex CLI
- `opencode` — open-source coding agent
- Plus: `copilot-cli`, `openhands`, `openhands-sdk`, `aider`, `goose`, `gemini-cli`, `hermes`, `qwen-coder`, `cursor-cli`, `cline-cli`, `mini-swe-agent`, `swe-agent`, `kimi-cli`, `rovodev-cli`, `trae-agent`, `antigravity-cli`
- Plus internal: `terminus-1`, `terminus-2`, `oracle` (runs `solution/solve.sh`, useful for sanity-checking a task), `nop`

LLM models are passed as LiteLLM-style strings: `anthropic/claude-opus-4-1`, `openai/gpt-4o`, etc. So model + agent are independent: `--agent claude-code --model anthropic/claude-sonnet-4-5`.

All three of our target harnesses (claude-code, codex, opencode) are first-class. **We do not need to write harness adapters.**

## MCP support — built in, but with a caveat

Harbor has **declarative, agent-agnostic MCP config**. In `task.toml`:

```toml
[[environment.mcp_servers]]
name = "mcp-server"
transport = "streamable-http"   # or "sse" or "stdio"
url = "http://mcp-server:8000/mcp"
# for stdio:
# command = "npx"
# args = ["-y", "some-mcp-server"]
```

Compatible agents auto-register these. Confirmed via `grep mcp_servers src/harbor/agents/installed/`: claude-code, codex, opencode, copilot-cli, cursor-cli, gemini-cli, goose, hermes, kimi-cli, qwen-coder, openhands, openhands-sdk, mini-swe-agent, antigravity-cli, openclaw — i.e. all the ones that matter.

Each agent translates the config to its native format. E.g. claude-code writes `~/.claude.json` with `{"mcpServers": {...}}` (see [`src/harbor/agents/installed/claude_code.py:1187`](https://github.com/harbor-framework/harbor/blob/main/src/harbor/agents/installed/claude_code.py)).

**Caveat — no auth headers in the config schema.** `MCPServerConfig` ([`src/harbor/models/task/config.py:485`](https://github.com/harbor-framework/harbor/blob/main/src/harbor/models/task/config.py)) has only `name`, `transport`, `url`, `command`, `args`. There is **no `headers` field**, so a Bearer token for a remote MCP (like `https://mcp.apify.com/`, GitHub MCP, Linear MCP, Notion MCP) cannot be passed through this declarative config today. Options to work around:

1. Run the MCP server **as a sidecar container** inside the task (the pattern shown in the cookbook). Auth is then internal to the container, and we control the env. Works for Apify if there's a self-hostable image, or for proxies. (This is what `recipes/mcp-tools` does, but with a local FastMCP server, not a remote one.)
2. Use `stdio` transport with a wrapper like `npx -y @modelcontextprotocol/server-github` and inject the token via `environment.env`. Many remote MCPs have stdio equivalents.
3. Have the agent itself register the MCP at runtime via its own config (e.g. write `~/.claude.json` in `solution.env` or as a setup step) — bypasses Harbor's MCP config entirely.
4. PR a `headers: dict[str, str]` field to `MCPServerConfig` upstream. Small change.

## Tracing, traces, metrics

- **Reward** is the primary signal. `reward.txt` for single float (0/1), `reward.json` for multi-metric. Harbor reads `reward.json` first, falls back to `.txt`.
- **Trajectories** in ATIF format are emitted by agents that opt in (`SUPPORTS_ATIF = True` on the agent class).
- **Logs** — `/logs/agent/` and `/logs/verifier/` are downloaded from each container to the host after the run.
- **Custom metrics** — see `examples/metrics/` and `packages/rewardkit/`. LLM-judge example at `examples/tasks/llm-judge-example/`.
- **Token / cost accounting** — handled via LiteLLM (which tracks per-call usage); how it surfaces in the trial summary is worth confirming in `src/harbor/metrics/` when we get there. The docs page on tracing is at https://www.harborframework.com/docs (see "Core Concepts").
- **Viewer UI** — `apps/viewer/` is a React Router + Vite app for browsing trial results. There's also `harbor view` and `harbor analyze` CLI commands.

## Useful CLI commands

```bash
harbor run -p path/to/task -a claude-code -m anthropic/claude-opus-4-1
harbor run --dataset terminal-bench@2.0 --agent codex --model openai/gpt-5 --n-concurrent 4
harbor run ... --env daytona --n-concurrent 100   # cloud
harbor datasets list
harbor init --task "<org>/<name>"                  # scaffold a new task
harbor run -t hello-world/hello-world -e daytona   # smoke test
```
