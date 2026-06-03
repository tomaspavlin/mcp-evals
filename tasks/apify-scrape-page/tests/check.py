from pathlib import Path

from rewardkit import criterion

EXPECTED_TITLE = "Example Domain"


@criterion
def page_title_matches(workspace: Path) -> bool:
    return (workspace / "result.txt").read_text().strip() == EXPECTED_TITLE
