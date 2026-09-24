"""What Windows itself has been told about animation and contrast.

Talk DAT! has always had its own "reduce motion" checkbox, and it has always
been the only thing consulted. That is the wrong shape for an accessibility
preference: somebody with a vestibular disorder sets *Windows* to stop
animating, once, in Settings > Accessibility > Visual effects, and expects every
application to have heard. Ours had not, so an app whose own source calls
unrequested motion "a symptom trigger" animated at them anyway until they found
our checkbox and set it a second time (X-536).

The system setting and the app setting are ORed, never substituted. The app's
checkbox has to keep working for someone who wants Windows animated and this
one still, and turning Windows' animation back on must not silently undo a
choice they made in our settings.

ctypes against user32 rather than a dependency: this is two documented
SystemParametersInfo reads, both cheap enough to call per animation, and adding
a package to the shipped bundle to ask them would cost more than it saves.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

#: "Show animations in Windows". The call reports whether animation is ENABLED,
#: so a False here means the person asked for stillness.
SPI_GETCLIENTAREAANIMATION = 0x1042

#: The high-contrast themes. HCF_HIGHCONTRASTON is the flag inside the struct
#: that this returns, which is why it needs a struct rather than a BOOL.
SPI_GETHIGHCONTRAST = 0x0042
HCF_HIGHCONTRASTON = 0x00000001


class _HIGHCONTRAST(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwFlags", wintypes.DWORD),
        ("lpszDefaultScheme", wintypes.LPWSTR),
    ]


def _on_windows() -> bool:
    return sys.platform == "win32"


def animations_are_switched_off() -> bool:
    """True when Windows has been asked not to animate.

    False on any other platform, and false whenever the question cannot be
    answered. Guessing "reduce motion" from a failed call would silently
    disable animation for everybody the first time this ran somewhere
    unexpected, and a preference nobody expressed is not a preference.
    """

    if not _on_windows():
        return False
    enabled = wintypes.BOOL()
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(enabled), 0
        )
    except (AttributeError, OSError, ValueError):
        return False
    if not ok:
        return False
    return not bool(enabled.value)


def high_contrast_is_on() -> bool:
    """True when Windows is running one of the high-contrast themes."""

    if not _on_windows():
        return False
    info = _HIGHCONTRAST()
    info.cbSize = ctypes.sizeof(_HIGHCONTRAST)
    try:
        ok = ctypes.windll.user32.SystemParametersInfoW(
            SPI_GETHIGHCONTRAST, ctypes.sizeof(_HIGHCONTRAST), ctypes.byref(info), 0
        )
    except (AttributeError, OSError, ValueError):
        return False
    if not ok:
        return False
    return bool(info.dwFlags & HCF_HIGHCONTRASTON)


__all__ = ["animations_are_switched_off", "high_contrast_is_on"]
