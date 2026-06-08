import shutil
from pathlib import Path

from mcp_evals.integrations.model import Integration


def materialize_environment(integration: Integration, task_path: Path) -> Path:
    """Replace `task_path/environment/` with a fresh copy of the integration's env.

    The target dir is fully cleared first so leftovers from a previous
    integration (e.g., the wrong proxy script after switching from github-mcp
    to apify-mcp) don't linger and pollute `dirhash(environment_dir)`, which
    remote sandboxes use to key template caches.

    The target dir is gitignored and entirely owned by materialize - hand-edits
    here will be discarded on the next run. Edit integrations/<name>/environment/
    instead.
    """
    if integration.environment_dir is None:
        raise ValueError(
            f"Integration '{integration.name}' has no environment/ dir to materialize"
        )
    if not task_path.is_dir():
        raise FileNotFoundError(f"Task path is not a directory: {task_path}")

    target = task_path / "environment"
    if target.exists() and not target.is_dir():
        raise NotADirectoryError(
            f"Expected a directory at {target}, found a file"
        )
    if target.is_dir():
        shutil.rmtree(target)
    shutil.copytree(integration.environment_dir, target)
    return target


def materialize_for_tasks(
    integration: Integration, task_paths: list[Path]
) -> list[Path]:
    return [materialize_environment(integration, p) for p in task_paths]


def discover_dataset_task_paths(dataset_path: Path) -> list[Path]:
    """List subdirectories of `dataset_path` that look like task dirs (have
    `task.toml`). Used when materializing for a --dataset-path run, since
    harbor's own discovery requires environment/ to already exist."""
    if not dataset_path.is_dir():
        raise FileNotFoundError(f"Dataset path is not a directory: {dataset_path}")
    return sorted(p for p in dataset_path.iterdir() if (p / "task.toml").is_file())
