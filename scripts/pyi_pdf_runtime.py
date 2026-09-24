"""Load the separately replaceable PDF library before the frozen fallback."""

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    folder = Path(sys._MEIPASS) / "pdf_runtime"
    if (folder / "fpdf" / "__init__.py").is_file():
        sys.path.insert(0, str(folder))
