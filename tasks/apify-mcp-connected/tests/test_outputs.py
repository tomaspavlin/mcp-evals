from pathlib import Path

OUTPUT = Path("/app/mcps.txt")


def test_output_file_exists():
    assert OUTPUT.exists(), f"{OUTPUT} not created"


def test_apify_listed():
    names = [line.strip() for line in OUTPUT.read_text().splitlines() if line.strip()]
    assert "apify" in names, f"'apify' not in {names!r}"
