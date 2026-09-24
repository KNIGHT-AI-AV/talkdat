from __future__ import annotations

import inspect
import unittest

from knight_flow.overlay import Overlay


class FollowerSidebarModelTests(unittest.TestCase):
    def test_destination_model_is_immutable_and_page_only(self) -> None:
        self.assertIsInstance(Overlay.SIDEBAR_DESTINATIONS, tuple)
        self.assertEqual(
            [row[0] for row in Overlay.SIDEBAR_DESTINATIONS],
            [
                "settings",
                "history",
                "scratchpad",
                "translation",
                "stats",
                "local_models",
                "account",
                "add_words",
                "mic_doctor",
            ],
        )
        excluded = {
            "more_features",
            "paste_last",
            "captions",
            "ramble",
            "scribe",
            "check_updates",
            "restart_app",
            "quit_app",
            "toggle_intensity",
            "feature_idea",
        }
        self.assertTrue(excluded.isdisjoint(row[0] for row in Overlay.SIDEBAR_DESTINATIONS))

    def test_every_destination_names_a_stable_zero_argument_page_callback(self) -> None:
        for action, _title, callback_name in Overlay.SIDEBAR_DESTINATIONS:
            with self.subTest(action=action):
                callback = getattr(Overlay, callback_name, None)
                self.assertTrue(callable(callback), callback_name)
                parameters = list(inspect.signature(callback).parameters.values())
                self.assertEqual([parameter.name for parameter in parameters], ["self"])

    def test_sidebar_builder_does_not_derive_rows_from_command_menu(self) -> None:
        source = inspect.getsource(Overlay._attach_menu_rail)
        self.assertIn("self._sidebar_destination_rows()", source)
        self.assertNotIn("self._context_menu_rows()", source)
        self.assertNotIn("self._activate_context_menu_action", source)


class FollowerSidebarGeometryTests(unittest.TestCase):
    def test_left_dock_remains_preferred_when_it_fits(self) -> None:
        geometry = Overlay._sidebar_docked_geometry(
            host_x=500,
            host_y=100,
            host_width=600,
            host_height=500,
            requested_width=220,
            work_area=(0, 0, 1600, 900),
        )
        self.assertEqual(geometry, (220, 500, 280, 100))

    def test_docks_right_when_left_has_insufficient_room(self) -> None:
        width, height, x, y = Overlay._sidebar_docked_geometry(
            host_x=40,
            host_y=90,
            host_width=600,
            host_height=500,
            requested_width=220,
            work_area=(0, 0, 1600, 900),
        )
        self.assertEqual((width, height), (220, 500))
        self.assertEqual((x, y), (640, 90))

    def test_narrow_side_shrinks_without_covering_host_or_leaving_work_area(self) -> None:
        left, top, right, bottom = (0, 0, 1000, 650)
        host_x, host_width = 300, 500
        width, height, x, y = Overlay._sidebar_docked_geometry(
            host_x=host_x,
            host_y=-30,
            host_width=host_width,
            host_height=900,
            requested_width=360,
            work_area=(left, top, right, bottom),
        )
        self.assertEqual((width, x), (300, 0))
        self.assertEqual((height, y), (650, 0))
        self.assertLessEqual(left, x)
        self.assertLessEqual(x + width, host_x)
        self.assertLessEqual(y + height, bottom)

    def test_high_scale_host_uses_complete_icon_rail_instead_of_clipped_labels(self) -> None:
        width, height, x, y = Overlay._sidebar_docked_geometry(
            host_x=100,
            host_y=0,
            host_width=2360,
            host_height=1440,
            requested_width=408,
            collapsed_width=60,
            work_area=(0, 0, 2560, 1440),
        )
        self.assertEqual((width, height), (60, 1440))
        self.assertEqual((x, y), (2460, 0))

    def test_attached_rail_switches_layout_without_overwriting_user_preference(self) -> None:
        source = inspect.getsource(Overlay._attach_menu_rail)
        self.assertIn("collapsed_width=rail_width", source)
        self.assertIn('"auto_collapsed": False', source)
        self.assertIn("def render_rail_layout(visually_open: bool)", source)
        self.assertIn('state["open"] and not auto_collapsed', source)
        self.assertIn('is_open and not state["auto_collapsed"]', source)

    def test_missing_work_area_preserves_historic_left_follow(self) -> None:
        self.assertEqual(
            Overlay._sidebar_docked_geometry(
                host_x=500,
                host_y=100,
                host_width=600,
                host_height=500,
                requested_width=220,
                work_area=None,
            ),
            (220, 500, 280, 100),
        )


class FollowerSidebarKeyboardTests(unittest.TestCase):
    def test_focus_navigation_wraps_in_both_directions(self) -> None:
        self.assertEqual(Overlay._sidebar_focus_index(0, -1, 10), 9)
        self.assertEqual(Overlay._sidebar_focus_index(9, 1, 10), 0)
        self.assertEqual(Overlay._sidebar_focus_index(4, 1, 10), 5)

    def test_rows_and_collapse_control_have_keyboard_contract(self) -> None:
        source = inspect.getsource(Overlay._attach_menu_rail)
        self.assertIn("toggle = FlatButton(", source)
        self.assertIn("row = FlatButton(", source)
        self.assertNotIn("label = tk.Label(", source)
        self.assertIn("row.configure(command=go)", source)
        self.assertIn("toggle.configure(command=toggle_open)", source)
        self.assertGreaterEqual(source.count("takefocus=1"), 2)
        for binding in ("<Return>", "<space>", "<Up>", "<Down>", "<FocusIn>", "<FocusOut>"):
            with self.subTest(binding=binding):
                self.assertIn(binding, source)
        self.assertIn("highlightbackground=focus_color", source)

    def test_open_width_uses_dpi_scale_and_rendered_title_measurement(self) -> None:
        source = inspect.getsource(Overlay._attach_menu_rail)
        self.assertIn("ui_scale.px(self.SIDEBAR_OPEN_WIDTH", source)
        self.assertIn("row_font.measure(title)", source)

    def test_short_hosts_get_a_scrollable_keyboard_revealing_destination_viewport(self) -> None:
        source = inspect.getsource(Overlay._attach_menu_rail)
        self.assertIn("items_canvas = tk.Canvas(", source)
        self.assertIn("items_scrollbar = ttk.Scrollbar(", source)
        self.assertIn("items_canvas.yview_scroll", source)
        self.assertIn("reveal_sidebar_row(row_shell)", source)
        self.assertIn("reveal_sidebar_row(target.master)", source)
        self.assertIn('widget.bind("<MouseWheel>", scroll_items', source)


if __name__ == "__main__":
    unittest.main()
