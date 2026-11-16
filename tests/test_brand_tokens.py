"""The brand comes from ``static/img/b_labs.jpeg``: teal on charcoal.

These tests protect the owner's review decision C: the interface accent is the
logo's teal, and the neutrals are charcoal, not the previous blue-slate scale.
They read the source stylesheet, not the generated build output.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
STYLES = REPO_ROOT / "styles" / "app.css"


def _token_block(selector: str) -> str:
    source = STYLES.read_text(encoding="utf-8")
    match = re.search(
        rf"{re.escape(selector)}\s*\{{(?P<body>.*?)\n\}}",
        source,
        flags=re.DOTALL,
    )
    assert match is not None, f"missing token block {selector}"
    return match.group("body")


def _token(block: str, name: str) -> str:
    match = re.search(rf"--{re.escape(name)}:\s*([^;]+);", block)
    assert match is not None, f"missing token --{name}"
    return match.group(1).strip()


def _oklch(value: str) -> tuple[float, float, float]:
    match = re.fullmatch(
        r"oklch\(\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s*\)", value
    )
    assert match is not None, f"not an oklch() token: {value}"
    return tuple(float(part) for part in match.groups())  # type: ignore[return-value]


def test_primary_is_the_b_labs_teal_in_both_themes() -> None:
    for selector in (":root", ".dark"):
        block = _token_block(selector)
        lightness, chroma, hue = _oklch(_token(block, "primary"))
        assert chroma >= 0.06, f"{selector}: primary is too grey"
        assert 170 <= hue <= 195, f"{selector}: primary hue is not teal"
        assert 0.4 <= lightness <= 0.9, f"{selector}: primary lightness is unusable"


def test_accent_is_a_mint_tint_of_the_same_hue() -> None:
    for selector in (":root", ".dark"):
        block = _token_block(selector)
        _, primary_chroma, primary_hue = _oklch(_token(block, "primary"))
        accent_lightness, accent_chroma, accent_hue = _oklch(_token(block, "accent"))
        assert abs(accent_hue - primary_hue) <= 12, f"{selector}: accent hue drift"
        assert accent_lightness != _oklch(_token(block, "primary"))[0]
        assert accent_chroma < primary_chroma


def test_neutrals_are_charcoal_not_blue() -> None:
    for selector in (":root", ".dark"):
        block = _token_block(selector)
        for name in ("background", "foreground", "card", "border"):
            _, chroma, _ = _oklch(_token(block, name))
            assert chroma <= 0.02, f"{selector}: --{name} is tinted, not charcoal"


def test_templates_do_not_use_raw_color_literals() -> None:
    """Quality gate C0.4: templates must use CSS variables/design tokens, not raw hex colors."""
    hex_pattern = re.compile(r"(?<!&)(#[0-9a-fA-F]{3,8})\b")
    offenders: list[str] = []

    templates_dir = REPO_ROOT / "templates"
    for template_path in templates_dir.rglob("*.html"):
        content = template_path.read_text(encoding="utf-8")
        # Ignore comments or inline CSS variable fallbacks like var(--logo-bg, #1A1A1A)
        stripped = re.sub(r"\{#-.*?-\#\}", "", content, flags=re.DOTALL)
        stripped = re.sub(r"var\([^)]+\)", "", stripped)
        matches = hex_pattern.findall(stripped)
        if matches:
            offenders.append(f"{template_path.name}: {matches}")

    assert not offenders, f"Templates with raw color literals (use CSS variables instead): {offenders}"
