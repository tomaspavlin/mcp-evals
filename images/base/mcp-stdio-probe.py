#!/usr/bin/env python3
"""Probe an MCP stdio server: send initialize + tools/list, assert tools exist.

Reproduces exactly what opencode/codex/claude-code do when they spawn an MCP
stdio child. If this probe succeeds, the harness will see >=1 tool too; if it
fails, the harness would silently drop the server, leaving the agent without
its tools (see docs/off-channel-call-analysis.md Cat 4).

Usage:
    mcp-stdio-probe.py [--retries N] [--timeout SEC] [--name LABEL] \\
        -- <proxy-cmd> [args...]

On failure, prints a `CONNECTOR_PROBE_FAILED: <label>: <reason>` line to stderr
and exits 1. The unique prefix lets us distinguish probe-failed trials from
agent crashes in trial.log / dashboard later.
"""
from __future__ import annotations

import argparse
import json
import os
import select
import subprocess
import sys
import time

INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "mcp-stdio-probe", "version": "0"},
    },
}
INITIALIZED = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
TOOLS_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}


def _send(stdin, frame: dict) -> None:
    stdin.write((json.dumps(frame) + "\n").encode())
    stdin.flush()


def _wait_for_id(stdout, target_id: int, deadline: float, buf: bytearray) -> tuple[dict | None, str | None]:
    """Read JSON-RPC frames from stdout until one matching target_id arrives.

    Returns (msg, None) on success, (None, reason) on timeout / closed stdout.
    `buf` is shared across calls so partial reads carry over.
    """
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        rlist, _, _ = select.select([stdout], [], [], remaining)
        if not rlist:
            return None, f"timed out waiting for id={target_id}"
        chunk = os.read(stdout.fileno(), 4096)
        if not chunk:
            return None, "proxy closed stdout"
        buf.extend(chunk)
        while b"\n" in buf:
            raw, _, rest = buf.partition(b"\n")
            del buf[:]
            buf.extend(rest)
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == target_id:
                return msg, None
    return None, f"timed out waiting for id={target_id}"


def probe_once(cmd: list[str], timeout: float) -> tuple[int, str | None]:
    """Run one probe attempt. Returns (n_tools, error_or_None).

    The remote MCP server uses an HTTP session bound to the initialize
    response, so requests must be serialized: initialize -> wait -> the rest.
    Pipelining all 3 frames at once gets the tools/list request rejected with
    "No valid session ID provided".
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        return 0, f"proxy not executable: {exc}"

    assert proc.stdin and proc.stdout
    deadline = time.monotonic() + timeout
    buf = bytearray()
    try:
        _send(proc.stdin, INIT)
        msg, err = _wait_for_id(proc.stdout, 1, deadline, buf)
        if err:
            return 0, f"initialize: {err}"
        if "error" in (msg or {}):
            return 0, f"initialize error: {msg['error'].get('message') or msg['error']}"

        _send(proc.stdin, INITIALIZED)
        _send(proc.stdin, TOOLS_LIST)
        msg, err = _wait_for_id(proc.stdout, 2, deadline, buf)
        if err:
            return 0, f"tools/list: {err}"
        if "error" in (msg or {}):
            return 0, f"tools/list error: {msg['error'].get('message') or msg['error']}"
        tools = (msg.get("result") or {}).get("tools") or []
        return len(tools), None
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--retries", type=int, default=1, help="extra attempts on failure")
    p.add_argument("--timeout", type=float, default=20.0, help="per-attempt wall clock")
    p.add_argument("--name", default="mcp", help="label used in error messages")
    p.add_argument("cmd", nargs=argparse.REMAINDER, help="-- <proxy-cmd> [args...]")
    args = p.parse_args()

    cmd = args.cmd
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("CONNECTOR_PROBE_FAILED: mcp-stdio-probe: no proxy command", file=sys.stderr)
        return 2

    last_err = "no attempts ran"
    for attempt in range(1, args.retries + 2):
        n, err = probe_once(cmd, args.timeout)
        if n >= 1:
            print(f"mcp-stdio-probe[{args.name}]: ok, {n} tools (attempt {attempt})")
            return 0
        last_err = err or "tools/list returned 0 tools"
        print(
            f"mcp-stdio-probe[{args.name}]: attempt {attempt} failed: {last_err}",
            file=sys.stderr,
        )
        if attempt < args.retries + 1:
            time.sleep(1.5)
    print(
        f"CONNECTOR_PROBE_FAILED: {args.name}: {last_err}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
