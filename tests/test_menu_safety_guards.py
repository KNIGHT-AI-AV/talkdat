from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "knight_flow" / "overlay.py"


def overlay_source() -> str:
    return OVERLAY.read_text(encoding="utf-8")


def nested_function(name: str) -> tuple[ast.FunctionDef, str]:
    source = overlay_source()
    tree = ast.parse(source)
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one {name!r} function, found {len(matches)}")
    return matches[0], source


def is_confirmation_guard(node: ast.stmt) -> bool:
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.UnaryOp):
        return False
    if not isinstance(node.test.op, ast.Not) or not isinstance(node.test.operand, ast.Call):
        return False
    call = node.test.operand
    return (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "messagebox"
        and call.func.attr == "askyesno"
        and len(node.body) == 1
        and isinstance(node.body[0], ast.Return)
    )


def confirmation_guard_with_status(function: ast.FunctionDef, source: str) -> ast.If:
    for node in function.body:
        block = ast.get_source_segment(source, node) or ""
        if isinstance(node, ast.If) and "messagebox.askyesno" in block:
            if any(isinstance(child, ast.Return) for child in node.body):
                return node
    raise AssertionError("confirmation guard with a cancel return was not found")


class SettingsMicrophoneIntentTests(unittest.TestCase):
    def test_only_a_deliberate_device_selection_starts_the_settings_meter(self) -> None:
        source = overlay_source()
        start = source.index("def refresh_live_meter(")
        end = source.index('self.add_window_disposer("settings", stop_live_meter)', start)
        block = source[start:end]

        self.assertIn("device_box.bind(", block)
        self.assertIn('"<<ComboboxSelected>>"', block)
        self.assertIn("stop_live_meter(restart=audio_tab_selected())", block)
        self.assertNotIn(
            'device_box.bind("<FocusOut>"',
            block,
            "moving focus must never start or restart a microphone stream",
        )
        self.assertIn("meter_leave_binding = notebook.bind(", block)
        self.assertIn('"<<NotebookTabChanged>>", stop_meter_when_leaving', block)


class DestructiveActionConfirmationTests(unittest.TestCase):
    def test_clear_text_history_confirms_before_touching_storage(self) -> None:
        function, source = nested_function("clear_history")
        self.assertTrue(is_confirmation_guard(function.body[0]))
        block = ast.get_source_segment(source, function) or ""
        self.assertIn("Clear text history?", block)
        self.assertIn("This cannot be undone.", block)
        self.assertIn("parent=window", block)
        # Find-more P0-6: the clear is history.clear_saved_text, shared with the web shell.
        self.assertLess(block.index("messagebox.askyesno"), block.index("clear_saved_text()"))

    def test_scratchpad_delete_confirms_before_clearing_or_deleting(self) -> None:
        function, source = nested_function("delete_tab")
        guards = [node for node in function.body if is_confirmation_guard(node)]
        self.assertEqual(len(guards), 1)
        guard = guards[0]
        block = ast.get_source_segment(source, function) or ""

        self.assertIn("Clear this note?", block)
        self.assertIn("Delete this note?", block)
        self.assertIn("This cannot be undone.", block)
        self.assertIn("parent=window", block)
        self.assertLess(guard.lineno, next(node.lineno for node in ast.walk(function) if isinstance(node, ast.Delete)))

    def test_downloaded_local_model_delete_names_impact_and_recovery(self) -> None:
        function, source = nested_function("remove_local_model")
        confirmation_guard_with_status(function, source)
        block = ast.get_source_segment(source, function) or ""

        self.assertIn("Delete local model?", block)
        self.assertIn("This is the active local model", block)
        self.assertIn("Recovery: choose Download", block)
        self.assertIn('default="no"', block)
        self.assertIn("parent=window", block)
        self.assertLess(block.index("messagebox.askyesno"), block.index("delete_local_model(model)"))

    def test_custom_model_removal_confirms_and_explains_that_files_remain(self) -> None:
        function, source = nested_function("remove_custom_model")
        confirmation_guard_with_status(function, source)
        block = ast.get_source_segment(source, function) or ""

        self.assertIn("Remove custom model?", block)
        self.assertIn("source files are not deleted", block)
        self.assertIn("Add the same Hugging Face id", block)
        self.assertIn('default="no"', block)
        self.assertIn("parent=window", block)


class TranslationWorkspaceActionTests(unittest.TestCase):
    def test_translation_has_one_truthful_copy_result_action(self) -> None:
        function, source = nested_function("open_translation")
        block = ast.get_source_segment(source, function) or ""

        self.assertEqual(block.count('text="Copy result"'), 1)
        self.assertNotIn('text="Copy"', block)
        self.assertIn('command=paste_result', block)
        self.assertIn('self.callbacks.get("translation_paste")', block)


if __name__ == "__main__":
    unittest.main()
