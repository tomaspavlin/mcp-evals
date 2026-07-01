"""Slide-ready cumulative-tokens/cost chart, one line per connector.

Reads trajectory.json across jobs, filters by task+model, groups by connector,
time-normalizes each trial to progress fraction 0..1, averages within a group,
then rescales x/y to (avg end time, avg end value) so the line endpoint IS the
group average. Exports SVG (+ optional PNG).

Usage:
    uv run python scripts/export_trial_chart.py \\
      --task connector-evals/apify-maps-place-info \\
      --model 'anthropic/claude-sonnet-5@preset/anthropic-provider-only' \\
      --y tokens \\
      --label mcp='raw MCP' --label mcpc=mcpc --label cli=CLI \\
      --out chart.svg
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import plotly.graph_objects as go

REPO_ROOT = Path(__file__).resolve().parents[1]

# Load metrics.py by file path (matches dashboard/app.py) so we don't trigger the
# package-level harbor monkey-patches and don't need the connector_evals venv.
_spec = importlib.util.spec_from_file_location(
    "connector_evals_metrics", REPO_ROOT / "src" / "connector_evals" / "metrics.py"
)
metrics_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(metrics_mod)

# Palette matches the reference mockup (teal / orange / slate). Extend if more
# connectors show up in one chart.
DEFAULT_PALETTE = ["#2ea0a1", "#c96a2b", "#5a6a7a", "#8b6ab8", "#b8a06a"]
DEFAULT_ORDER = ["mcp", "mcpc", "cli", "cli+skill"]


def read_trajectory(traj_path: Path, model_name: str | None) -> tuple[list[float], list[int], list[float]]:
    """Return (t_seconds, cum_tokens, cum_cost) arrays. Empty on any failure."""
    try:
        steps = json.loads(traj_path.read_text()).get("steps", [])
    except (json.JSONDecodeError, OSError):
        return [], [], []
    pricing = metrics_mod.pricing_for(model_name)
    ts, toks, costs = [], [], []
    t0: datetime | None = None
    cum_tok = 0
    cum_cost = 0.0
    for s in steps:
        raw_ts = s.get("timestamp")
        if not raw_ts:
            continue
        when = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        if t0 is None:
            t0 = when
        m = s.get("metrics") or {}
        cum_tok += (m.get("prompt_tokens") or 0) + (m.get("completion_tokens") or 0)
        if pricing:
            cache_write = ((m.get("extra") or {}).get("cache_creation_input_tokens")) or 0
            cum_cost += metrics_mod.apply_pricing(
                pricing,
                m.get("prompt_tokens") or 0,
                m.get("completion_tokens") or 0,
                m.get("cached_tokens") or 0,
                cache_write,
            )
        ts.append((when - t0).total_seconds())
        toks.append(cum_tok)
        costs.append(cum_cost)
    return ts, toks, costs


def scan_trials(jobs_dir: Path, task_name: str, model_name: str) -> list[dict]:
    """Yield {job, trial, connector, model, task, traj_path} for matching trials.

    Uses config.json + result.json directly (JobScanner would drag in harbor).
    Connector is parsed from verifier env (CONNECTOR_EVALS_CONNECTOR /
    CONNECTOR_EVALS_CONNECTORS_JSON) with a legacy fallback via the job name.
    """
    out = []
    for job_dir in sorted(jobs_dir.iterdir()):
        if not job_dir.is_dir():
            continue
        for trial_dir in sorted(job_dir.iterdir()):
            if not trial_dir.is_dir():
                continue
            cfg = _read_json(trial_dir / "config.json")
            res = _read_json(trial_dir / "result.json")
            if not cfg or not res:
                continue
            if res.get("task_name") != task_name:
                continue
            if (cfg.get("agent") or {}).get("model_name") != model_name:
                continue
            connector = _connector_from(cfg, job_dir.name)
            traj = trial_dir / "agent" / "trajectory.json"
            if not traj.exists():
                continue
            out.append({
                "job": job_dir.name,
                "trial": trial_dir.name,
                "connector": connector,
                "traj_path": traj,
            })
    return out


def _read_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _connector_from(cfg: dict, job_name: str) -> str:
    env = ((cfg.get("verifier") or {}).get("env") or {})
    js = env.get("CONNECTOR_EVALS_CONNECTORS_JSON")
    if js:
        try:
            values = sorted(set(json.loads(js).values()))
            if len(values) == 1:
                return _norm(values[0])
            return "hybrid"
        except (json.JSONDecodeError, AttributeError):
            pass
    single = env.get("CONNECTOR_EVALS_CONNECTOR") or env.get("EXPECTED_CONNECTOR")
    if single:
        return _norm(single)
    for tok in job_name.split("-"):
        if tok in {"mcp", "mcpc", "cli", "skill", "cli+skill"}:
            return _norm(tok)
    return "?"


def _norm(c: str) -> str:
    return "cli+skill" if c == "skill" else c


def normalize_and_average(trials: list[dict], y_key: str, resample_n: int = 200) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Time-normalize each trial to 0..1, average, rescale to (avg_t_end, avg_y_end).

    Returns (x, y, avg_t_end, avg_y_end). x, y have length resample_n+1.
    """
    if not trials:
        return np.array([]), np.array([]), 0.0, 0.0
    frac_grid = np.linspace(0.0, 1.0, resample_n + 1)
    stacked = []
    end_ts = []
    end_ys = []
    for tr in trials:
        ts, toks, costs = read_trajectory(tr["traj_path"], tr.get("model_name"))
        ys = toks if y_key == "tokens" else costs
        if len(ts) < 2 or ts[-1] <= 0:
            continue
        t_arr = np.array(ts, dtype=float)
        y_arr = np.array(ys, dtype=float)
        # Prepend origin so the curve starts at (0,0) — reflects "before first step".
        t_arr = np.insert(t_arr, 0, 0.0)
        y_arr = np.insert(y_arr, 0, 0.0)
        fracs = t_arr / t_arr[-1]
        # Normalize y to end at 1.0 for shape averaging; we rescale by avg endpoint later.
        y_norm = y_arr / y_arr[-1] if y_arr[-1] > 0 else y_arr
        resampled = np.interp(frac_grid, fracs, y_norm)
        stacked.append(resampled)
        end_ts.append(t_arr[-1])
        end_ys.append(y_arr[-1])
    if not stacked:
        return np.array([]), np.array([]), 0.0, 0.0
    mean_shape = np.mean(np.vstack(stacked), axis=0)
    if len(stacked) >= 2:
        # Edge-padded rolling mean so boundaries stay on the curve (a naive
        # convolve 'same' averages against phantom zeros and dips the tails).
        kernel = np.ones(5) / 5
        padded = np.pad(mean_shape, 2, mode="edge")
        smoothed = np.convolve(padded, kernel, mode="valid")
    else:
        smoothed = mean_shape
    avg_t = float(np.mean(end_ts))
    avg_y = float(np.mean(end_ys))
    x = frac_grid * avg_t
    y = smoothed * avg_y
    return x, y, avg_t, avg_y


def build_figure(
    groups: list[dict],
    y_key: str,
    width: int,
    height: int,
    palette: list[str],
) -> go.Figure:
    fig = go.Figure()
    max_x = 0.0
    max_y = 0.0
    for i, g in enumerate(groups):
        color = g.get("color") or palette[i % len(palette)]
        x, y = g["x"], g["y"]
        if x.size == 0:
            continue
        max_x = max(max_x, float(x[-1]))
        max_y = max(max_y, float(y[-1]))
        fig.add_trace(go.Scatter(
            x=x, y=y,
            mode="lines",
            line=dict(color=color, width=4, shape="spline", smoothing=1.0),
            hoverinfo="skip",
            showlegend=False,
        ))
        # Endpoint: filled dot + larger open ring (like the mockup).
        fig.add_trace(go.Scatter(
            x=[x[-1]], y=[y[-1]],
            mode="markers",
            marker=dict(size=14, color="white", line=dict(color=color, width=2.5)),
            hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=[x[-1]], y=[y[-1]],
            mode="markers+text",
            marker=dict(size=8, color=color),
            text=[f"  {g['label']}"],
            textposition="middle right",
            textfont=dict(family="JetBrains Mono, Menlo, monospace", size=18, color=color),
            hoverinfo="skip", showlegend=False,
        ))

    # Pad right so the end labels don't clip.
    x_pad = 1.18
    y_pad = 1.10
    axis_title_font = dict(size=18, color="#333")
    xaxis = dict(
        title=dict(text="time", font=axis_title_font, standoff=14),
        range=[0, max_x * x_pad if max_x > 0 else 1],
        showgrid=False, zeroline=False, showline=False,
        ticks="outside", tickcolor="#bbb",
        ticksuffix="s",
        tickfont=dict(size=16, color="#333"),
    )
    if y_key == "cost":
        yaxis = dict(
            title=dict(text="cumulative cost (USD)", font=axis_title_font, standoff=14),
            range=[0, max_y * y_pad if max_y > 0 else 1],
            showgrid=True, gridcolor="#eee", zeroline=False, showline=False,
            tickprefix="$", tickformat=".2f",
            tickfont=dict(size=16, color="#333"),
        )
    else:
        yaxis = dict(
            title=dict(text="cumulative tokens", font=axis_title_font, standoff=14),
            range=[0, max_y * y_pad if max_y > 0 else 1],
            showgrid=True, gridcolor="#eee", zeroline=False, showline=False,
            tickformat="~s",
            tickfont=dict(size=16, color="#333"),
        )
    fig.update_layout(
        width=width, height=height,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Helvetica, Arial, sans-serif", size=16),
        margin=dict(l=100, r=110, t=40, b=80),
        xaxis=xaxis, yaxis=yaxis,
        showlegend=False,
    )
    return fig


def parse_labels(items: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        if "=" not in item:
            raise SystemExit(f"--label expects key=value, got {item!r}")
        k, v = item.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jobs-dir", type=Path, default=REPO_ROOT / "jobs")
    ap.add_argument("--task", required=True, help="task_name to filter (e.g. connector-evals/apify-maps-place-info)")
    ap.add_argument("--model", required=True, help="agent model_name to filter (exact match)")
    ap.add_argument("--y", choices=["tokens", "cost"], default="tokens")
    ap.add_argument("--connector", action="append", default=None,
                    help="restrict to these connectors (repeatable); default = all found")
    ap.add_argument("--label", action="append", default=[],
                    help="connector label override, key=value (repeatable, e.g. mcp='raw MCP')")
    ap.add_argument("--color", action="append", default=[],
                    help="per-connector color override, key=hex (repeatable, e.g. mcp=#5a6a7a)")
    ap.add_argument("--order", default=None,
                    help="comma-separated connector draw order; default = mcp,mcpc,cli,cli+skill")
    ap.add_argument("--out", type=Path, default=Path("chart.svg"))
    ap.add_argument("--width", type=int, default=1600)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--also-png", action="store_true", help="also write <out>.png next to the svg")
    args = ap.parse_args()

    trials = scan_trials(args.jobs_dir, args.task, args.model)
    for tr in trials:
        tr["model_name"] = args.model  # for pricing_for()

    if not trials:
        print(f"no trials matched task={args.task!r} model={args.model!r} in {args.jobs_dir}", file=sys.stderr)
        sys.exit(1)

    by_conn: dict[str, list[dict]] = {}
    for tr in trials:
        by_conn.setdefault(tr["connector"], []).append(tr)

    wanted = args.connector if args.connector else list(by_conn.keys())
    order_list = args.order.split(",") if args.order else DEFAULT_ORDER
    def order_key(c: str) -> tuple[int, str]:
        return (order_list.index(c) if c in order_list else 999, c)

    labels = parse_labels(args.label)
    colors_override = parse_labels(args.color)
    groups: list[dict] = []
    print(f"Found {len(trials)} trials across {len(by_conn)} connector(s):")
    for connector in sorted([c for c in wanted if c in by_conn], key=order_key):
        conn_trials = by_conn[connector]
        x, y, avg_t, avg_y = normalize_and_average(conn_trials, args.y)
        if x.size == 0:
            print(f"  {connector}: {len(conn_trials)} trials but no usable trajectories, skipping")
            continue
        y_str = f"{avg_y:,.0f} tok" if args.y == "tokens" else f"${avg_y:,.4f}"
        print(f"  {connector}: n={len(conn_trials)}  avg end = {avg_t:.1f}s / {y_str}")
        groups.append({
            "label": labels.get(connector, connector),
            "color": colors_override.get(connector),
            "x": x, "y": y,
            "avg_t": avg_t, "avg_y": avg_y,
        })

    if not groups:
        print("no groups to plot", file=sys.stderr)
        sys.exit(1)

    fig = build_figure(groups, args.y, args.width, args.height, DEFAULT_PALETTE)
    fig.write_image(str(args.out), width=args.width, height=args.height, scale=2)
    print(f"wrote {args.out}")
    if args.also_png:
        png_path = args.out.with_suffix(".png")
        fig.write_image(str(png_path), width=args.width, height=args.height, scale=2)
        print(f"wrote {png_path}")


if __name__ == "__main__":
    main()
