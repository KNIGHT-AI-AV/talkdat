"""T1 mutation tests: a fault in any guard must make the T1 suite fail.

Two families, each built from the real source so a change to the code cannot
leave a stale mutant behind:

* every refusal guard of ``decide`` and ``insertion_proved``, removed one at a
  time (found in the syntax tree, so a new guard is covered without editing
  this file);
* named faults in the Mac adapter (and the shared final read-back), each a
  single exact edit of the source that must be found exactly once.

A mutant is "caught" when the T1 suite (KILLERS) has at least one failure or
error with it in place. Every mutant must be caught; the summary line printed
at the end gives the count.
"""
from __future__ import annotations

import ast
import contextlib
import copy
import inspect
import io
import sys
import types
import unittest
from unittest import mock

from knight_flow import verified_replace as vr
from knight_flow import verified_target_mac as vtm

KILLERS = ("tests.test_verified_replace", "tests.test_verified_target", "tests.test_verified_target_mac")

# name -> (module, the exact text, its replacement, the names whose definition it changes)
ADAPTER_FAULTS = {
    "skip the selection read-back": (vtm, '''        landed = ax.attribute(element, "AXSelectedTextRange")
        made = replace(made, landed=landed if _is_range(landed) else None)
        if record is not None:
            record(made)
        if landed != (caret - units, units):
            return None, made
        back = ax.attribute(element, "AXSelectedText")
        if back != text:
            return None, made
        return back, made
''', '''        made = replace(made, landed=(caret - units, units))
        if record is not None:
            record(made)
        return text, made
''', ("select_before_caret",)),
    "skip the caret restore on a failed proof": (
        vtm, "        self._write(lambda: restore_caret(self._ax, self._made, pasted=self._pasted), False)\n",
        "        return None\n", ("MacTarget",)),
    "forget a write that outlived its wait": (
        vtm, "        self._settle()  # a select still running may yet land; let it, then undo it\n"
             "        self._write(lambda: restore_caret(",
        "        self._write(lambda: restore_caret(", ("MacTarget",)),
    "code-point offsets instead of UTF-16": (
        vtm, '    return len(str(text).encode("utf-16-le", "surrogatepass")) // 2\n',
        "    return len(str(text))\n", ("utf16_len",)),
    "paste without a proved selection": (vtm, '''        if self._made is None or not self._run(lambda: selection_still(self._ax, self._made), False):
            return False
''', "", ("MacTarget",)),
    "delete by count (select by count over text nobody read)": (vtm, '''        if ax.string_for_range(element, caret - units, units) != text:
            return None, None
''', "", ("select_before_caret",)),
    "skip the final read-back": (vr, '''    if (after.ok and after.window == now.window and after.element == now.element and after.collapsed
            and expected_left.endswith(_norm(after.left)) and _norm(after.left).endswith(_norm(polished))
            and _norm(after.right) == _norm(now.right)):
''', "    if True:\n", ("replace_if_proved",)),
    # Beyond the six the GO named: the rest of what keeps the Mac reads honest.
    "skip the re-check after a read": (vtm, '''        latest = ax.focused()
        if latest is None or not ax.same(element, latest):
            return UNREAD
        if ax.attribute(element, "AXSelectedTextRange") != selected:
            return UNREAD
''', "", ("read_target",)),
    "read a password field": (vtm, '''        if ax.attribute(element, "AXSubrole") == SECURE_SUBROLE:
            # Never read a password field: not its text, not its length.
            return TargetRead(ok=True, window=window, element=token, password=True)
''', "", ("read_target",)),
    "treat terminals and remote desktops as targets": (
        vtm, "    if is_terminal_app(lowered) or lowered in REMOTE_APPS:\n        return True\n", "",
        ("unsupported_app",)),
    "restore over the person's own selection": (
        vtm, "        if not made.ours(current):\n            return True\n", "", ("restore_caret",)),
    "accept an answer for a different range": (
        vtm, "        if utf16_len(left) != reach or utf16_len(right) != right_reach:\n"
             "            return UNREAD  # the app answered a different range than the one asked for\n",
        "", ("read_target",)),
}


def run_killers() -> unittest.TestResult:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in KILLERS)
    return unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)


def build(module: types.ModuleType, source: str, changed: tuple[str, ...]) -> dict[str, object]:
    """The changed definitions, compiled from ``source`` in a namespace where
    every OTHER name is the real module's own object (classes included), so a
    mutant differs from the real code in its fault and nothing else."""
    namespace: dict[str, object] = {"__name__": module.__name__, "__package__": module.__package__,
                                    "__file__": module.__file__}
    exec(compile(source, module.__file__, "exec"), namespace)
    for name, value in vars(module).items():
        if name not in changed and not name.startswith("__"):
            namespace[name] = value
    return {name: namespace[name] for name in changed}


@contextlib.contextmanager
def swapped_in(module: types.ModuleType, replacements: dict[str, object]):
    """Each real definition replaced by its mutant wherever it is bound: in its
    own module and in every product or test module that imported it by name."""
    with contextlib.ExitStack() as stack:
        for name, mutant in replacements.items():
            real = getattr(module, name)
            for other in list(sys.modules.values()):
                other_name = getattr(other, "__name__", "") or ""
                if not other_name.startswith(("knight_flow", "tests")):
                    continue
                for key, value in list(vars(other).items()):
                    if value is real:
                        stack.enter_context(mock.patch.object(other, key, mutant))
        yield


def guard_mutants(function: str) -> list[tuple[str, str]]:
    """(label, source) for ``function`` with each refusal guard removed in turn."""
    tree = ast.parse(inspect.getsource(vr))
    target = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == function)
    guards = []
    for index, node in enumerate(target.body):
        if isinstance(node, ast.If) and len(node.body) == 1 and isinstance(node.body[0], ast.Return):
            value = node.body[0].value
            if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "Decision":
                reason = ast.unparse(value.args[1]).strip("'\"")
            elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                reason = value.value
            else:
                continue
            guards.append((index, reason))
    mutants = []
    for index, reason in guards:
        mutated = copy.deepcopy(tree)
        body = next(node for node in mutated.body
                    if isinstance(node, ast.FunctionDef) and node.name == function).body
        del body[index]
        mutants.append((f"{function}: drop the {reason!r} guard (statement {index})", ast.unparse(mutated)))
    return mutants


class EveryMutantIsCaught(unittest.TestCase):
    summary: dict[str, tuple[int, int]] = {}

    @classmethod
    def tearDownClass(cls) -> None:
        line = ", ".join(f"{family} {caught}/{total}" for family, (caught, total) in cls.summary.items())
        print(f"\nT1 mutants caught: {line}", file=sys.stderr)

    def assert_all_caught(self, family: str, mutants: list[tuple[str, types.ModuleType, dict[str, object]]]):
        baseline = run_killers()
        self.assertTrue(baseline.wasSuccessful(), "the T1 suite must pass before mutants mean anything")
        survivors = []
        for label, module, replacements in mutants:
            with swapped_in(module, replacements):
                result = run_killers()
            if result.wasSuccessful():
                survivors.append(label)
        self.summary[family] = (len(mutants) - len(survivors), len(mutants))
        self.assertEqual(survivors, [], f"{family}: mutants nobody caught")

    def test_every_decide_guard(self):
        mutants = [(label, vr, build(vr, source, ("decide",))) for label, source in guard_mutants("decide")]
        self.assertGreaterEqual(len(mutants), 12)
        self.assert_all_caught("decide", mutants)

    def test_every_insertion_guard(self):
        mutants = [(label, vr, build(vr, source, ("insertion_proved",)))
                   for label, source in guard_mutants("insertion_proved")]
        self.assertGreaterEqual(len(mutants), 6)
        self.assert_all_caught("insertion_proved", mutants)

    def test_every_adapter_fault(self):
        mutants = []
        for label, (module, old, new, changed) in ADAPTER_FAULTS.items():
            source = inspect.getsource(module)
            self.assertEqual(source.count(old), 1, f"{label}: the code it mutates has changed; update the mutant")
            mutants.append((label, module, build(module, source.replace(old, new), changed)))
        self.assert_all_caught("adapter", mutants)


if __name__ == "__main__":
    unittest.main()
