import shutil
from pathlib import Path

BASE_IMAGE_DIR = Path("images/base")


def materialize_environment(task_path: Path, base_image_dir: Path = BASE_IMAGE_DIR) -> Path:
    """Replace `task_path/environment/` with a fresh copy of `base_image_dir`.

    Every task uses the same base image (all CLIs and MCP proxies pre-installed);
    channel selection happens at runtime via mcp_servers / instruction append /
    setup script, not at image build time. Copying the same dir into every
    task means dirhash() is stable across runs and the sandbox template cache
    stays hot.

    The target dir is gitignored and entirely owned by materialize - hand-edits
    here will be discarded on the next run. Edit images/base/ instead.
    """
    if not task_path.is_dir():
        raise FileNotFoundError(f"Task path is not a directory: {task_path}")
    if not base_image_dir.is_dir():
        raise FileNotFoundError(f"Base image dir not found: {base_image_dir}")

    target = task_path / "environment"
    if target.exists() and not target.is_dir():
        raise NotADirectoryError(
            f"Expected a directory at {target}, found a file"
        )
    if target.is_dir():
        shutil.rmtree(target)
    shutil.copytree(base_image_dir, target)
    return target


def materialize_for_tasks(
    task_paths: list[Path], base_image_dir: Path = BASE_IMAGE_DIR
) -> list[Path]:
    return [materialize_environment(p, base_image_dir) for p in task_paths]


def discover_dataset_task_paths(dataset_path: Path) -> list[Path]:
    """List subdirectories of `dataset_path` that look like task dirs (have
    `task.toml`). Used when materializing for a --dataset-path run, since
    harbor's own discovery requires environment/ to already exist."""
    if not dataset_path.is_dir():
        raise FileNotFoundError(f"Dataset path is not a directory: {dataset_path}")
    return sorted(p for p in dataset_path.iterdir() if (p / "task.toml").is_file())
