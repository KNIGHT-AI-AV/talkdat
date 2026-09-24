"""Three lies the Translate feature told, and the guards that keep them fixed.

1. The workspace receipt said "Translated locally with TranslateGemma" even
   when Talk DAT! Cloud did the work -- and cloud is the default engine for
   everyone (X-77), so most customers were told the exact opposite of where
   their text went. The receipt must be derived from the engine that actually
   ran, read off the result: managed translations come back stamped with the
   managed model id, which is never a local model.

2. Choosing the LOCAL engine in Settings was silently reverted to cloud the
   next time the Translate workspace opened. The workspace's one-time
   local-to-managed migration keys on `engine_user_chosen` being absent, and
   the workspace save plants that flag -- but the Settings save never did, so
   a choice made in Settings did not count as a choice.

3. The Ramble failure toast said "Your words are in History -- nothing is
   lost", but the ramble path returns from finish_session before add_history
   ever runs. The words are actually in the live transcript draft the session
   wrote just before handing off -- unless transcript history is off, in which
   case the draft was deliberately cleared (X-222) and no copy exists.

These are structural assertions, not presence checks: each one requires the
fixed statement to sit where it executes (a conditional message assignment, an
assignment inside the save function, a call inside the failure handler), so
pasting the right words into a comment or a docstring cannot satisfy them.
Absence checks walk AST string constants, which never include comments.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from knight_flow.translation import TRANSLATION_MODELS

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"
APP = ROOT / "knight_flow" / "app.py"

# The model id translation.py stamps on every managed-cloud result. The UI
# reads the engine off this stamp, which only works while the id can never
# collide with a local model.
MANAGED_MODEL_STAMP = "gemini-3.5-flash-lite"


def _function_node(path: Path, *name_chain: str) -> ast.FunctionDef:
    """The AST node for a (possibly nested) function, found by name chain."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    scope: ast.AST = tree
    for name in name_chain:
        for node in ast.walk(scope):
            if isinstance(node, ast.FunctionDef) and node.name == name:
                scope = node
                break
        else:
            raise AssertionError(f"{name} not found in {path.name} (chain {name_chain})")
    assert isinstance(scope, ast.FunctionDef)
    return scope


def _string_constants(node: ast.AST) -> list[str]:
    """Every literal string that EXECUTES in this function.

    Comments are not in the AST at all, so an absence check against this list
    cannot be defeated (or falsely tripped) by prose.
    """
    return [
        n.value
        for n in ast.walk(node)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]


class TheReceiptNamesTheEngineThatRanTests(unittest.TestCase):
    """Fix 1: overlay.open_translation -> run_translation -> worker."""

    def setUp(self) -> None:
        self.worker = _function_node(OVERLAY, "open_translation", "run_translation", "worker")

    def _message_assignment(self) -> ast.Assign:
        for node in ast.walk(self.worker):
            if (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "message"
            ):
                return node
        raise AssertionError("run_translation's worker no longer assigns `message`")

    def test_the_message_is_conditional_on_the_engine(self) -> None:
        """The defect was one unconditional f-string: `Translated locally
        with ...` no matter which engine ran. The fix is a conditional, so a
        plain (non-conditional) assignment is the defect returning."""
        assignment = self._message_assignment()
        self.assertIsInstance(
            assignment.value,
            ast.IfExp,
            "the receipt is assigned unconditionally again -- it will claim "
            "one engine for both, and cloud is the default for everyone",
        )

    def test_one_branch_says_cloud_and_the_other_says_local(self) -> None:
        assignment = self._message_assignment()
        value = assignment.value
        self.assertIsInstance(value, ast.IfExp)
        branch_texts = (
            " ".join(_string_constants(value.body)),
            " ".join(_string_constants(value.orelse)),
        )
        self.assertTrue(
            any("Translated on this computer" in text for text in branch_texts),
            "no branch of the receipt says where the translation ran",
        )
        self.assertTrue(
            any("Translated locally with" in text for text in branch_texts),
            "no branch of the receipt keeps the local wording",
        )

    def test_the_managed_stamp_can_never_be_a_local_model(self) -> None:
        """The premise of the derivation: the UI decides local-vs-cloud by
        looking the result model up in the local catalogue. If the managed
        stamp ever appears in TRANSLATION_MODELS, cloud reads as local and
        the original lie returns with this guard still green."""
        self.assertNotIn(MANAGED_MODEL_STAMP, TRANSLATION_MODELS)


def _sets_engine_user_chosen(func: ast.FunctionDef) -> bool:
    """True when the function executes translation_config["engine_user_chosen"] = True."""
    for node in ast.walk(func):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Name)
            and target.value.id == "translation_config"
            and isinstance(target.slice, ast.Constant)
            and target.slice.value == "engine_user_chosen"
            and isinstance(node.value, ast.Constant)
            and node.value.value is True
        ):
            return True
    return False


class BothSavePathsPlantTheChosenFlagTests(unittest.TestCase):
    """Fix 2: the migration keys on the flag's ABSENCE, so every path that
    writes translation_config["engine"] must also plant the flag. There are
    exactly two: the workspace save and the Settings save. The Settings save
    was the one that did not, which silently reverted a local choice made in
    Settings back to cloud the next time the workspace opened."""

    def test_the_settings_save_sets_it(self) -> None:
        save = _function_node(OVERLAY, "open_settings", "save")
        self.assertTrue(
            _sets_engine_user_chosen(save),
            "open_settings.save() writes translation_config['engine'] without "
            "engine_user_chosen = True, so the workspace migration will treat "
            "a Settings engine choice as a stale default and revert it to cloud",
        )

    def test_the_workspace_save_still_sets_it(self) -> None:
        save = _function_node(OVERLAY, "open_translation", "save_translation_preferences")
        self.assertTrue(
            _sets_engine_user_chosen(save),
            "save_translation_preferences no longer plants engine_user_chosen",
        )

    def test_the_migration_that_needed_the_flag_is_gone(self) -> None:
        """X-516: the other half of the contract, inverted.

        The flag existed because a one-time migration rewrote a stored
        "local" engine to "managed" unless someone had chosen local on
        purpose. With no managed engine, that migration would move every
        install onto a value that raises engine_invalid, so it was removed.

        The two assertions above now guard a flag nothing reads, which is
        harmless, and this asserts the reason: no branch of open_translation
        may assign the managed engine again."""
        workspace = _function_node(OVERLAY, "open_translation")
        for node in ast.walk(workspace):
            if isinstance(node, ast.Assign):
                for text in _string_constants(node.value):
                    self.assertNotEqual(
                        text, "managed",
                        "open_translation assigns the managed engine again; it errors now",
                    )


class RambleFailureSaysWhereTheWordsAreTests(unittest.TestCase):
    """Fix 3 of this file (finding 4): app.finish_ramble's failure handler."""

    def setUp(self) -> None:
        self.finish_ramble = _function_node(APP, "finish_ramble")

    def test_it_no_longer_claims_history(self) -> None:
        """finish_ramble returns before add_history, so any executed string
        placing the words "in History" is a promise the code cannot keep."""
        offenders = [s for s in _string_constants(self.finish_ramble) if "in History" in s]
        self.assertEqual(
            offenders, [],
            "the ramble failure toast claims History again, but this path "
            "returns before add_history ever runs",
        )

    def test_it_checks_the_live_draft_rather_than_asserting_it(self) -> None:
        """The truthful location is the live transcript draft -- and only when
        it exists, because X-222 clears it when transcript history is off. The
        message must therefore be conditional on an .exists() probe, with a
        live-draft claim on one side and the no-copy truth on the other."""
        for node in ast.walk(self.finish_ramble):
            if not isinstance(node, ast.IfExp):
                continue
            test = node.test
            if not (
                isinstance(test, ast.Call)
                and isinstance(test.func, ast.Attribute)
                and test.func.attr == "exists"
            ):
                continue
            branch_texts = (
                " ".join(_string_constants(node.body)),
                " ".join(_string_constants(node.orelse)),
            )
            if any("live draft" in text for text in branch_texts) and any(
                "history is off" in text for text in branch_texts
            ):
                return
        self.fail(
            "finish_ramble's failure message is not derived from whether the "
            "live draft actually exists -- it will either claim a file that "
            "was cleared or hide the one place the words survive"
        )

    def test_the_draft_path_comes_from_the_one_true_source(self) -> None:
        """The claim must point at live_draft_path(), the same path the
        session writer uses -- a hand-typed filename would drift."""
        for node in ast.walk(self.finish_ramble):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "live_draft_path"
            ):
                return
        self.fail("finish_ramble never calls live_draft_path()")


if __name__ == "__main__":
    unittest.main()
