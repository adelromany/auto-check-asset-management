"""Validate the handover Word templates in FORMS_DIR."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import FORMS_DIR
from app.domain.form_fill import TemplateError, fill_engineer


def main() -> int:
    failed = False
    for path in sorted(Path(FORMS_DIR).glob("*.docx")):
        try:
            fill_engineer(path.read_bytes(), "Template Check")
        except TemplateError as exc:
            print(f"{path.name}: {exc}")
            failed = True
        else:
            print(f"{path.name}: OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
