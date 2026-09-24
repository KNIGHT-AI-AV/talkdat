"""Font family names, importable before anything heavy.

The UI headers need family names at module import, and brand_font must not
run its platform registration calls that early (AddFontResourceExW at import
hangs detached processes -- its own header says so). This module is the
import-safe source of truth: names only, per platform, no side effects.
"""

from __future__ import annotations

import sys

_MAC = sys.platform == "darwin"

UI_FAMILY = "SF Pro Text" if _MAC else "Segoe UI"
UI_SEMIBOLD_FAMILY = "SF Pro Text Semibold" if _MAC else "Segoe UI Semibold"
MONO_FAMILY = "Menlo" if _MAC else "Consolas"
