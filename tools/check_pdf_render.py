"""Convert both production form templates and report their PDF page counts."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.pdf_render import docx_to_pdf  # noqa: E402

failed = False
for name in ("Mylo.docx", "B.tech.docx"):
    pdf = docx_to_pdf((ROOT / "forms" / name).read_bytes())
    if not pdf:
        print(f"FAIL {name}")
        failed = True
        continue
    pages = len(re.findall(rb"/Type\s*/Page\b", pdf))
    print(f"OK {name}: {pages} page(s)")
raise SystemExit(1 if failed else 0)
