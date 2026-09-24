from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "knight_flow" / "app.py"


class ScheduledMethodsExistTests(unittest.TestCase):
    """Every `self.X` handed to a timer must exist on the class.

    0.4.76 shipped `after(4500, self.maybe_show_trial_moment)` with no such
    method: the patch that was meant to add both died between them, and the
    full test suite stayed green because nothing anywhere constructs the real
    application object -- tests build Overlay, never TalkDatApp.run(). Every
    launch died with AttributeError before the Pill appeared, and the launch
    probe counted the crash DIALOG as a live process.

    This is the cheapest possible guard against that class: no Tk, no audio,
    just the promise that a scheduled name is a defined name.
    """

    def test_every_scheduled_self_method_is_defined(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        tree = ast.parse(source)
        defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        scheduled = set(re.findall(r"\bafter(?:_idle)?\(\s*[0-9_]*\s*,?\s*self\.([a-zA-Z_][a-zA-Z0-9_]*)\s*[\),]", source))
        missing = sorted(name for name in scheduled if name not in defined)
        self.assertEqual(missing, [], f"scheduled but never defined on the app: {missing}")


if __name__ == "__main__":
    unittest.main()
