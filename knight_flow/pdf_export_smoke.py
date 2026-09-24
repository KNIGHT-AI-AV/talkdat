"""Synthetic export acceptance for the actual packaged desktop executable."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path


def run() -> None:
    destination = os.environ.get("TALK_DAT_EXPORT_SMOKE_DIR", "").strip()
    if not destination:
        raise SystemExit("Set TALK_DAT_EXPORT_SMOKE_DIR to a new, private test folder.")
    folder = Path(destination)
    folder.mkdir(parents=True, exist_ok=False)
    receipt = {
        "success": False,
        "frozen": bool(getattr(sys, "frozen", False)),
        "files": [],
    }
    try:
        import fpdf
        from .ramble_export import render
        from .export_report import render_report_pdf
        from .export_files import save_new_export

        source = (
            "Le coût est 3 425,75 €.\n请在星期五之前完成。\nمرحبا بالعالم\n"
            "नमस्ते दुनिया\n👨‍👩‍👧‍👦 👍🏿\n<script>alert(1)</script> & (profit)\n\n"
            "  Indentation\tcolumn\n\n" + "The complete report paragraph. " * 120
        )
        when = dt.datetime(2026, 9, 20, 12, 30)
        for format in ("pdf", "pdf:midnight", "word", "markdown", "text"):
            data, extension = render(source, format, when)
            name = "ramble-" + format.replace(":", "-") + "." + extension
            path = save_new_export(folder, name, data)
            receipt["files"].append(
                {
                    "name": path.name,
                    "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        data = render_report_pdf(source)
        path = save_new_export(folder, "report.pdf", data)
        receipt["files"].append(
            {
                "name": path.name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        (folder / "source.txt").write_text(source, encoding="utf-8")
        receipt.update(success=True, library=str(fpdf.__file__))
    except Exception as error:
        receipt["error"] = str(error)
    (folder / "receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    if not receipt["success"]:
        raise SystemExit(1)
