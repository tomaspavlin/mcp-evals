from pathlib import Path

from rewardkit import criterion

EXPECTED_TITLE = "Example Domain"


@criterion
def page_title_matches(workspace: Path) -> bool:
    f = workspace / "result.txt"
    return f.is_file() and f.read_text().strip() == EXPECTED_TITLE
