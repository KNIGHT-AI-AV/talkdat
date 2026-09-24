"""What to call the machine a person is using, in copy they will read.

This lives on main ON PURPOSE, and it is the whole point of the module.

The constant used to exist only on `mac-port`, inside `mac_support.py`. Main
therefore wrote "this PC" everywhere, `mac-port` fixed those strings after every
merge, and the next merge brought them straight back. Twice now somebody has
sat down and converted the same sentences: twelve of them in an earlier pass
over `overlay.py` and `ui/onboarding.py`, then twenty-two more on 2026-09-21,
having found them only because a Mac user was told about their PC.

Main is the branch both platforms build from, so the answer has to be here.
`mac_support` re-exports these names, so every existing `mac_support.THIS_COMPUTER`
call site keeps working and the Mac port inherits correct copy instead of
correcting it.

There is deliberately nothing macOS-specific in this module -- no AppKit, no
lazy imports, nothing that a Windows build would rather not import. It answers
one question, and `sys.platform` is the whole of the evidence.
"""
from __future__ import annotations

import sys

#: True on macOS. Mirrors mac_support.IS_MAC, which is defined the same way;
#: this module cannot import that one, because that one is the Mac port's.
IS_MAC = sys.platform == "darwin"

#: Mid-sentence: "Audio stays on this Mac", "Delete from this PC".
THIS_COMPUTER = "this Mac" if IS_MAC else "this PC"

#: Sentence-initial, and as a standalone label.
#:
#: Only the first character may move. `.capitalize()` lowercases the rest and
#: renders "This mac"; `.title()` renders "this PC" as "This Pc". Both have
#: shipped in other products and both look like a typo rather than a platform.
THIS_COMPUTER_SENTENCE = THIS_COMPUTER[0].upper() + THIS_COMPUTER[1:]

#: The key that runs a command or sends a message: Return on a Mac keyboard.
ENTER_KEY = "Return" if IS_MAC else "Enter"
