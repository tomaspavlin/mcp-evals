# Harbor Task Example: MCP-using task

This is the closest existing example to what we want to build. Source: [`harbor-cookbook/harbor_cookbook/recipes/mcp-tools/`](https://github.com/harbor-framework/harbor-cookbook/tree/main/harbor_cookbook/recipes/mcp-tools). Mirror in main repo: [`harbor/examples/tasks/hello-mcp/`](https://github.com/harbor-framework/harbor/tree/main/examples/tasks/hello-mcp). Official tutorial: [MCP Server Task](https://www.harborframework.com/docs/tutorials/mcp-server-task).

## What it does

The agent is told an MCP server is running at `http://mcp-server:8000/mcp` exposing two tools. The agent must connect, call both tools, and write the returned values to two files. A pytest verifier checks the file contents.

This pattern - declarative MCP config + sidecar container + pytest verifier reading filesystem state - is **exactly** the shape of our eval tasks.

## Directory layout

```
mcp-tools/
├── README.md
├── task.toml                       # declares MCP server, resource limits
├── instruction.md                  # natural-language prompt for the agent
├── environment/
│   ├── Dockerfile                  # agent's container
│   ├── docker-compose.yaml         # adds the MCP sidecar
│   └── mcp-server/
│       ├── Dockerfile              # MCP server's container
│       └── server.py               # FastMCP server
├── tests/
│   ├── test.sh                     # verifier entrypoint
│   └── test_outputs.py             # pytest checks
└── solution/
    └── solve.sh                    # reference solution (for `oracle` agent)
```

## `task.toml` - the declarative core

```toml
version = "1.0"

[verifier]
timeout_sec = 600.0

[agent]
timeout_sec = 600.0

[environment]
build_timeout_sec = 600.0
cpus = 1
memory_mb = 2048
storage_mb = 10240

[[environment.mcp_servers]]
name = "mcp-server"
transport = "streamable-http"
url = "http://mcp-server:8000/mcp"
```

The `[[environment.mcp_servers]]` array is read by Harbor and forwarded to whichever agent runs. For `claude-code` it ends up in `~/.claude.json`; for `codex`, `opencode`, etc. each agent class handles its own translation.

Supported transports: `"sse"`, `"streamable-http"` (alias: `"http"`), `"stdio"`. URL is required for network transports; `command`+`args` for stdio.

## `instruction.md`

```markdown
There is an MCP server running at `http://mcp-server:8000/mcp` that exposes two tools:

- `get_secret` - returns a secret value
- `get_timestamp` - returns the server's startup timestamp

Your task:

1. Connect to the MCP server
2. Call both tools
3. Write the secret to `/app/secret.txt`
4. Write the timestamp to `/app/timestamp.txt`

Write each value exactly as returned by the tool, with no additional formatting.
```

Pure natural language. No special syntax. This is what the agent sees.

## `environment/docker-compose.yaml` - sidecar pattern

```yaml
# Merged on top of Harbor's base compose config.
# Harbor auto-configures the `main` service (agent container);
# you only specify overrides + extra services.
services:
  main:
    depends_on:
      mcp-server:
        condition: service_healthy

  mcp-server:
    build:
      context: ./mcp-server
    expose:
      - "8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import socket; s=socket.create_connection(('localhost',8000),timeout=2); s.close()"]
      interval: 2s
      timeout: 5s
      retries: 15
      start_period: 5s
```

Key idea: **`main` is the agent's container, autoconfigured by Harbor.** You add `depends_on` and any sidecar services. They share a Docker network, addressable by service name (`mcp-server`).

**Limitation:** Docker Compose tasks only work with `--env docker` (local). Cloud providers (Modal, E2B, ...) currently only support single-Dockerfile environments.

## `environment/mcp-server/server.py` - the sidecar MCP

```python
# /// script
# requires-python = ">=3.12"
# dependencies = ["fastmcp"]
# ///
from datetime import datetime, timezone
from fastmcp import FastMCP

mcp = FastMCP("mcp-tools")
SECRET_VALUE = "cookbook-mcp-secret-42"
STARTUP_TIME = datetime.now(timezone.utc).isoformat()

@mcp.tool()
def get_secret() -> str:
    return SECRET_VALUE

@mcp.tool()
def get_timestamp() -> str:
    return STARTUP_TIME

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

This is a stand-in for the real MCP. **For our project we have two options:**
1. Run the **real** remote MCP as a sidecar (if it's self-hostable / has a Docker image, e.g. for Apify or GitHub MCP).
2. Run a **mock** MCP sidecar with deterministic data - better for reproducibility (no rate limits, no live data drift) but worse for ecological validity.

## `tests/test.sh` - verifier entrypoint

```bash
#!/bin/bash
apt-get update
apt-get install -y curl
curl -LsSf https://astral.sh/uv/0.9.7/install.sh | sh
source $HOME/.local/bin/env

uvx \
  --with pytest==8.4.1 \
  --with pytest-json-ctrf==0.3.5 \
  pytest --ctrf /logs/verifier/ctrf.json /tests/test_outputs.py -rA

if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
```

Reward contract: write a number to `/logs/verifier/reward.txt`. `1.0` = success, `0.0` = failure. Anything else floats also work. For per-criterion scoring, write `reward.json` instead.

## `tests/test_outputs.py`

```python
from pathlib import Path

SECRET_VALUE = "cookbook-mcp-secret-42"

def test_secret_file_exists():
    assert Path("/app/secret.txt").exists()

def test_secret_file_contents():
    content = Path("/app/secret.txt").read_text().strip()
    assert content == SECRET_VALUE

def test_timestamp_file_exists():
    assert Path("/app/timestamp.txt").exists()

def test_timestamp_file_not_empty():
    content = Path("/app/timestamp.txt").read_text().strip()
    assert len(content) > 0
```

Standard pytest. The verifier runs in the same container as the agent by default ("shared" mode), so it sees the files the agent created. For tasks where the verifier needs hidden state, use `[verifier.environment]` for a "separate" container.

## Running it

```bash
# Smoke test with the oracle (runs solution/solve.sh)
harbor run -p harbor_cookbook/recipes/mcp-tools -a oracle

# Real eval with claude-code
harbor run -p harbor_cookbook/recipes/mcp-tools \
  --agent claude-code \
  --model anthropic/claude-sonnet-4-6

# Compare across agents
harbor run -p harbor_cookbook/recipes/mcp-tools -a claude-code -m anthropic/claude-opus-4-1
harbor run -p harbor_cookbook/recipes/mcp-tools -a codex      -m openai/gpt-5
harbor run -p harbor_cookbook/recipes/mcp-tools -a opencode   -m anthropic/claude-sonnet-4-6
```

## Verdict - this is our template

For each MCP/CLI/skill alternative we want to eval, we make a task directory with:

- `task.toml` - declares which MCP (if any) is available to the agent
- `instruction.md` - the user-facing prompt (same across MCP/CLI/skill variants)
- `environment/Dockerfile` (+ `docker-compose.yaml` if MCP sidecar) - sets up the world
- `tests/test.sh` + `test_outputs.py` - checks success
- `solution/solve.sh` - optional reference for oracle sanity check

To compare an MCP vs CLI vs skill alternative for the same task, we'd make three sibling tasks with the same instruction + tests but different `environment/` setups (one with MCP sidecar, one with CLI tool installed, one with a skill mounted). Or one task with three variants chosen via config - Harbor's [sweeps](https://www.harborframework.com/docs) (`harbor sweeps`) may be the right primitive here, worth investigating once we have a single task working.
