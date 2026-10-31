from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_windows_guide_environment_table_matches_config_and_example():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    config = (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "deployment" / "INSTALL-WINDOWS.md").read_text(
        encoding="utf-8"
    )
    example_vars = set(re.findall(r"^([A-Z][A-Z0-9_]*)=", example, re.M))
    table = guide.split("| Variable | Purpose / example | Where to get it | Required? |", 1)[1]
    table = table.split("\n\n", 1)[0]
    guide_vars = set(re.findall(r"^\s*\| `([A-Z][A-Z0-9_]*)` \|", table, re.M))
    assert example_vars <= guide_vars, f"Missing from guide table: {sorted(example_vars - guide_vars)}"
    config_vars = set(re.findall(r"^([A-Z][A-Z0-9_]*)\s*=\s*os\.getenv", config, re.M))
    config_vars |= set(re.findall(r"^([A-Z][A-Z0-9_]*)\s*=\s*\($", config, re.M))
    assert guide_vars <= config_vars | example_vars, (
        f"Guide lists unknown settings: {sorted(guide_vars - config_vars - example_vars)}"
    )
