from __future__ import annotations

import sys
import unittest

from knight_flow.win32_chrome import (
    AUXILIARY_CHROME,
    DWMWA_WINDOW_CORNER_PREFERENCE,
    DWMWCP_ROUND,
    DWMWCP_ROUNDSMALL,
    DWMWCP_DONOTROUND,
    SQUARE_CHROME,
    UTILITY_CHROME,
    WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW,
    WS_EX_TRANSPARENT,
    apply_no_activate_style,
    apply_shaped_window_region,
    apply_window_chrome,
    monitor_work_area_for_window,
    move_window_no_activate,
    native_toplevel_handle,
    set_dwm_int_attribute,
)


class FakeWindow:
    def __init__(self, client: int = 101) -> None:
        self.client = client

    def winfo_id(self) -> int:
        return self.client


class FakeChromeApi:
    def __init__(self) -> None:
        self.roots = {101: 202, 102: 303}
        self.clear_calls: list[int] = []
        self.set_dwm_calls: list[tuple[int, int, int]] = []
        self.get_dwm_calls: list[tuple[int, int]] = []
        self.created: list[tuple[int, int, int]] = []
        self.set_region_calls: list[tuple[int, int]] = []
        self.deleted: list[int] = []
        self.dwm_succeeds = True
        self.readback: int | None = None
        self.region_succeeds = True
        self.styles = {202: 0, 303: 0}
        self.set_style_calls: list[tuple[int, int]] = []
        self.set_pos_calls: list[tuple[int, int, int, int, int, int, int]] = []
        self.work_areas = {202: (-1920, 0, 0, 1080), 303: (0, 0, 2560, 1440)}

    def root_handle(self, client: int) -> int:
        return self.roots[int(client)]

    def clear_region(self, hwnd: int) -> bool:
        self.clear_calls.append(int(hwnd))
        return True

    def set_dwm_int(self, hwnd: int, attribute: int, value: int) -> bool:
        self.set_dwm_calls.append((int(hwnd), int(attribute), int(value)))
        return self.dwm_succeeds

    def get_dwm_int(self, hwnd: int, attribute: int) -> int | None:
        self.get_dwm_calls.append((int(hwnd), int(attribute)))
        if self.readback is not None:
            return self.readback
        if not self.set_dwm_calls:
            return None
        return self.set_dwm_calls[-1][2]

    def create_round_region(self, width: int, height: int, diameter: int) -> int:
        self.created.append((int(width), int(height), int(diameter)))
        return 404

    def set_region(self, hwnd: int, region: int) -> bool:
        self.set_region_calls.append((int(hwnd), int(region)))
        return self.region_succeeds

    def delete_region(self, region: int) -> None:
        self.deleted.append(int(region))

    def get_extended_style(self, hwnd: int) -> int:
        return int(self.styles[int(hwnd)])

    def set_extended_style(self, hwnd: int, style: int) -> bool:
        self.set_style_calls.append((int(hwnd), int(style)))
        self.styles[int(hwnd)] = int(style)
        return True

    def set_window_pos(
        self,
        hwnd: int,
        insert_after: int,
        x: int,
        y: int,
        width: int,
        height: int,
        flags: int,
    ) -> bool:
        self.set_pos_calls.append(
            (
                int(hwnd),
                int(insert_after),
                int(x),
                int(y),
                int(width),
                int(height),
                int(flags),
            )
        )
        return True

    def monitor_work_area(self, hwnd: int) -> tuple[int, int, int, int] | None:
        return self.work_areas.get(int(hwnd))


class NativeChromePolicyTests(unittest.TestCase):
    def test_it_resolves_the_visible_outer_handle(self) -> None:
        api = FakeChromeApi()
        self.assertEqual(native_toplevel_handle(FakeWindow(), api=api), 202)

    def test_windows_11_utility_acknowledges_dwm_hint_on_outer_handle(self) -> None:
        api = FakeChromeApi()
        receipt = apply_window_chrome(
            FakeWindow(),
            UTILITY_CHROME,
            api=api,
            platform_name="win32",
            windows_build=22_000,
        )

        self.assertEqual(receipt.mode, "dwm_hint")
        self.assertEqual(receipt.hwnd, 202)
        self.assertEqual(receipt.preference, DWMWCP_ROUND)
        self.assertEqual(
            api.set_dwm_calls,
            [(202, DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND)],
        )
        self.assertEqual(
            api.get_dwm_calls,
            [(202, DWMWA_WINDOW_CORNER_PREFERENCE)],
        )

    def test_windows_11_auxiliary_uses_small_native_radius(self) -> None:
        api = FakeChromeApi()
        receipt = apply_window_chrome(
            FakeWindow(),
            AUXILIARY_CHROME,
            api=api,
            platform_name="win32",
            windows_build=22_000,
        )
        self.assertEqual(receipt.preference, DWMWCP_ROUNDSMALL)
        self.assertEqual(api.set_dwm_calls[-1][-1], DWMWCP_ROUNDSMALL)

    def test_attached_or_broadcast_surface_explicitly_stays_square(self) -> None:
        api = FakeChromeApi()
        receipt = apply_window_chrome(
            FakeWindow(),
            SQUARE_CHROME,
            api=api,
            platform_name="win32",
            windows_build=22_000,
        )
        self.assertEqual(receipt.mode, "square")
        self.assertEqual(receipt.preference, DWMWCP_DONOTROUND)
        self.assertEqual(api.set_dwm_calls[-1][-1], DWMWCP_DONOTROUND)

    def test_windows_10_is_deliberately_square_not_gdi_rounded(self) -> None:
        api = FakeChromeApi()
        receipt = apply_window_chrome(
            FakeWindow(),
            UTILITY_CHROME,
            api=api,
            platform_name="win32",
            windows_build=19_045,
        )

        self.assertEqual(receipt.mode, "square")
        self.assertEqual(api.set_dwm_calls, [])
        self.assertEqual(api.created, [])

    def test_a_failed_or_unverified_dwm_request_remains_retryable(self) -> None:
        for succeeds, readback in ((False, None), (True, DWMWCP_ROUNDSMALL)):
            with self.subTest(succeeds=succeeds, readback=readback):
                api = FakeChromeApi()
                api.dwm_succeeds = succeeds
                api.readback = readback
                receipt = apply_window_chrome(
                    FakeWindow(),
                    UTILITY_CHROME,
                    api=api,
                    platform_name="win32",
                    windows_build=22_000,
                )
                self.assertEqual(receipt.mode, "retry")

    def test_a_transient_dwm_failure_retries_on_the_same_outer_handle(self) -> None:
        api = FakeChromeApi()
        api.dwm_succeeds = False
        window = FakeWindow()
        first = apply_window_chrome(
            window,
            UTILITY_CHROME,
            api=api,
            platform_name="win32",
            windows_build=22_000,
        )
        self.assertEqual(first.mode, "retry")

        api.dwm_succeeds = True
        second = apply_window_chrome(
            window,
            UTILITY_CHROME,
            api=api,
            platform_name="win32",
            windows_build=22_000,
        )
        self.assertEqual(second.mode, "dwm_hint")
        self.assertEqual(len(api.set_dwm_calls), 2)

    def test_exact_handle_receipt_is_idempotent_but_wrapper_change_reapplies(self) -> None:
        api = FakeChromeApi()
        window = FakeWindow()
        first = apply_window_chrome(
            window,
            AUXILIARY_CHROME,
            api=api,
            platform_name="win32",
            windows_build=22_000,
        )
        second = apply_window_chrome(
            window,
            AUXILIARY_CHROME,
            api=api,
            platform_name="win32",
            windows_build=22_000,
        )
        self.assertIs(first, second)
        self.assertEqual(len(api.set_dwm_calls), 1)

        window.client = 102
        third = apply_window_chrome(
            window,
            AUXILIARY_CHROME,
            api=api,
            platform_name="win32",
            windows_build=22_000,
        )
        self.assertEqual(third.hwnd, 303)
        self.assertEqual(len(api.set_dwm_calls), 2)

    def test_other_dwm_attributes_also_target_only_the_outer_handle(self) -> None:
        api = FakeChromeApi()
        self.assertTrue(set_dwm_int_attribute(FakeWindow(), 20, 1, api=api))
        self.assertEqual(api.set_dwm_calls, [(202, 20, 1)])

    def test_no_activate_and_click_through_share_the_same_outer_handle(self) -> None:
        api = FakeChromeApi()
        self.assertTrue(
            apply_no_activate_style(FakeWindow(), click_through=True, api=api)
        )
        required = WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
        self.assertEqual(api.set_style_calls, [(202, required)])
        self.assertEqual(api.set_pos_calls[0][0], 202)
        self.assertEqual(api.styles[202] & required, required)

    def test_pointer_safe_move_and_monitor_lookup_use_the_outer_handle(self) -> None:
        api = FakeChromeApi()
        self.assertTrue(move_window_no_activate(FakeWindow(), -1900, 24, api=api))
        self.assertEqual(api.set_pos_calls[0][0:4], (202, 0, -1900, 24))
        self.assertEqual(
            monitor_work_area_for_window(FakeWindow(), api=api),
            (-1920, 0, 0, 1080),
        )

    def test_shaped_pill_transfers_one_region_to_only_the_outer_handle(self) -> None:
        api = FakeChromeApi()
        applied = apply_shaped_window_region(
            FakeWindow(),
            240,
            58,
            29,
            api=api,
            platform_name="win32",
        )
        self.assertTrue(applied)
        self.assertEqual(api.created, [(240, 58, 58)])
        self.assertEqual(api.set_region_calls, [(202, 404)])
        self.assertEqual(api.deleted, [], "Windows owns a successfully transferred HRGN")

    def test_failed_region_transfer_deletes_the_unowned_region(self) -> None:
        api = FakeChromeApi()
        api.region_succeeds = False
        applied = apply_shaped_window_region(
            FakeWindow(),
            240,
            58,
            29,
            api=api,
            platform_name="win32",
        )
        self.assertFalse(applied)
        self.assertEqual(api.deleted, [404])

    def test_unknown_role_is_rejected_before_platform_calls(self) -> None:
        with self.assertRaises(ValueError):
            apply_window_chrome(
                FakeWindow(),
                "mystery",
                api=FakeChromeApi(),
                platform_name="win32",
                windows_build=22_000,
            )


@unittest.skipUnless(sys.platform == "win32", "real Win32 style readback")
class NativeChromeWindowsIntegrationTests(unittest.TestCase):
    def test_real_outer_window_acknowledges_no_activate_and_click_through(self) -> None:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        window = tk.Toplevel(root)
        window.withdraw()
        try:
            window.update_idletasks()
            self.assertGreater(native_toplevel_handle(window), 0)
            self.assertTrue(
                apply_no_activate_style(window, click_through=True),
                "the typed style call or its outer-HWND readback failed",
            )
        finally:
            window.destroy()
            root.destroy()


if __name__ == "__main__":
    unittest.main()
