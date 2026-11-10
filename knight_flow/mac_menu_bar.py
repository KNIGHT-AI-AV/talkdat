"""The menu bar item on macOS, built with AppKit instead of pystray.

pystray cannot do this job here. Its macOS backend builds an NSStatusItem, and
AppKit refuses to instantiate one off the main thread --

    NSInternalInconsistencyException - NSWindow should only be instantiated on
    the main thread!

-- while TrayController runs its icon on a worker thread, because that is what
Windows needs. The exception is swallowed by the `except Exception: return` at
the end of TrayController._run, so on macOS the menu bar item silently never
appeared and nothing said why.

The main thread belongs to Tk's mainloop, and on Aqua that mainloop *is* an
NSRunLoop, so the status item can be created directly from it. Everything here
must therefore be called on the Tk thread; `start()` takes the Tk root and uses
`after` to guarantee that regardless of the caller.

The menu mirrors TrayController's exactly, in the same order, so the two
platforms offer the same thing in the place each one's users look for it
(0.4.177 IA phase 2: Pause listening and Show the Pill are check items whose
labels never flip, and the update row shows only while an update waits). It
matters more here than on Windows: the app is LSUIElement, so there is no Dock
icon and no application menu, and without this the only way to quit is the
Pill's context menu.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .icon import make_tray_image

log = logging.getLogger(__name__)

Callback = Callable[[], None]

# (label, callback name). A None label is a separator. 0.4.177 IA phase 2
# (IA-SCHEMATIC.md section 2): item for item the tray's menu (tray.py), names,
# order and groups; test_mac_menu_bar reads the tray's code to hold them equal.
# "__update__" is the one computed label: Install update <version>, shown only
# while an update waits (Check for updates is on Home and Help).
MENU_LAYOUT: tuple[tuple[str | None, str], ...] = (
    ("Open Talk DAT!", "show"),
    ("Start hands-free dictation", "hands_free"),
    ("Pause listening", "pause"),
    ("Cancel what's recording", "cancel"),
    (None, ""),
    ("History", "history"),
    ("Scratchpad", "scratchpad"),
    ("Translate", "translation"),
    (None, ""),
    ("Show the Pill", "toggle_pill"),
    ("Settings", "settings"),
    ("Help", "help"),
    (None, ""),
    ("__update__", "install_update"),
    (None, ""),
    ("Restart Talk DAT!", "restart"),
    ("Panic stop", "panic"),
    (None, ""),
    ("Quit Talk DAT!", "quit"),
)
# R6: check items whose labels never flip, keyed by action: the state each one shows.
CHECK_ITEMS = {"pause": "paused", "toggle_pill": "pill_shown"}
# NSControlStateValueOn and NSControlStateValueOff, without importing AppKit here.
ON, OFF = 1, 0
# The divider under the update row, hidden with it so no two dividers meet.
UPDATE_FENCE = "__update_fence__"


_menu_target_class: Any = None


def _menu_target_type() -> Any:
    """The Objective-C class that receives menu clicks, defined exactly once.

    Objective-C classes are registered globally by name, so defining this inside
    the function that builds the menu raises

        objc.error: _MenuTarget is overriding existing Objective-C class

    the second time anything builds one -- which is every app restart, not just
    a second test. Built lazily because it cannot be declared until AppKit is
    imported, and importing AppKit at module scope would cost every Windows
    build the import.
    """
    global _menu_target_class
    if _menu_target_class is not None:
        return _menu_target_class

    import AppKit
    import objc

    class _MenuTarget(AppKit.NSObject):
        @objc.python_method
        def bind(self, owner: "MacMenuBar") -> None:
            self._owner = owner

        def invoke_(self, sender: Any) -> None:  # noqa: N802 - ObjC selector
            owner = getattr(self, "_owner", None)
            if owner is None:
                return
            owner._call(str(sender.representedObject() or ""))

    _menu_target_class = _MenuTarget
    return _menu_target_class


def _status_image(size: int = 18) -> Any:
    """The tray artwork as an NSImage sized for the menu bar.

    Marked as a template image so macOS tints it for light and dark menu bars
    and for the highlighted state, which a plain colour image does not follow.
    """
    import AppKit
    from Foundation import NSData

    from io import BytesIO

    image = make_tray_image()
    image = image.convert("RGBA").resize((size, size))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    data = NSData.dataWithBytes_length_(buffer.getvalue(), len(buffer.getvalue()))
    ns_image = AppKit.NSImage.alloc().initWithData_(data)
    ns_image.setSize_(AppKit.NSMakeSize(size, size))
    ns_image.setTemplate_(True)
    return ns_image


class MacMenuBar:
    """TrayController's interface, backed by NSStatusItem."""

    def __init__(self, callbacks: dict[str, Callback]) -> None:
        self.callbacks = callbacks
        self.paused = False
        self.update_available = ""
        # Show the Pill's check: the person's own choice, told by the app, as on the tray.
        self.pill_shown = True
        self._root: Any = None
        self._status_item: Any = None
        self._target: Any = None
        # NSMenuItem does not retain its target, so the handler object has to be
        # held here; letting it be collected turns every click into a no-op.
        self._items: dict[str, Any] = {}

    def _update_label(self) -> str:
        return f"Install update {self.update_available}"

    def status_text(self) -> str:
        """The icon's tooltip, word for word the tray's (R18): Status left the menu for Help's Status panel."""
        return "Talk DAT!: paused" if self.paused else "Talk DAT!: ready"

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self._refresh_menu()

    def set_pill_shown(self, shown: bool) -> None:
        self.pill_shown = bool(shown)
        self._refresh_menu()

    def set_update_available(self, version: str) -> None:
        self.update_available = str(version or "")
        self._refresh_menu()

    def start(self, root: Any = None) -> None:
        """Create the status item on the Tk thread.

        `root` is the Tk root. It is optional only so this matches
        TrayController.start(); without it the item cannot be created safely and
        the call becomes a logged no-op rather than a crash on a random thread.
        """
        if root is None:
            log.warning("menu bar not started: no Tk root to create it on")
            return
        self._root = root
        root.after(0, self._create)

    def _create(self) -> None:
        try:
            import AppKit
            import objc

            target = _menu_target_type().alloc().init()
            target.bind(self)
            self._target = target

            bar = AppKit.NSStatusBar.systemStatusBar()
            item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
            button = item.button()
            if button is not None:
                try:
                    button.setImage_(_status_image())
                except Exception:
                    # A missing icon is survivable; a menu bar item with no way
                    # to reach it is not.
                    button.setTitle_("Talk DAT!")
                button.setToolTip_(self.status_text())

            menu = AppKit.NSMenu.alloc().init()
            menu.setAutoenablesItems_(False)
            after_update = False
            for label, name in MENU_LAYOUT:
                if label is None:
                    separator = AppKit.NSMenuItem.separatorItem()
                    menu.addItem_(separator)
                    if after_update:
                        self._items[UPDATE_FENCE] = separator
                    after_update = False
                    continue
                after_update = label == "__update__"
                title = self._dynamic_title(label)
                entry = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    title, objc.selector(None, selector=b"invoke:"), ""
                )
                entry.setTarget_(target)
                entry.setRepresentedObject_(name)
                entry.setEnabled_(True)
                menu.addItem_(entry)
                self._items[label] = entry
            item.setMenu_(menu)
            self._status_item = item
            self._apply_state()
            log.info("menu bar item created")
        except Exception:
            # Logged rather than swallowed: a missing menu bar item on an app
            # with no Dock icon leaves no obvious way to quit, and the previous
            # silent failure is what hid that.
            log.exception("menu bar item could not be created")

    def _dynamic_title(self, label: str) -> str:
        if label == "__update__":
            return self._update_label()
        return label

    def _apply_state(self) -> None:
        """Show the state on the Tk thread: the two checks, the update row and its fence, and the tooltip.

        Labels never flip (R6); only the checks, the update row's version and what is hidden change.
        """
        items = self._items
        for label, name in MENU_LAYOUT:
            entry = items.get(label) if label is not None else None
            if entry is None:
                continue
            try:
                if name in CHECK_ITEMS:
                    entry.setState_(ON if getattr(self, CHECK_ITEMS[name]) else OFF)
                elif label == "__update__":
                    entry.setTitle_(self._update_label())
                    entry.setHidden_(not self.update_available)
            except Exception:
                pass
        fence = items.get(UPDATE_FENCE)
        if fence is not None:
            try:
                fence.setHidden_(not self.update_available)
            except Exception:
                pass
        try:
            button = self._status_item.button() if self._status_item is not None else None
            if button is not None:
                button.setToolTip_(self.status_text())
        except Exception:
            pass

    def _refresh_menu(self) -> None:
        """Show a state change, on the Tk thread."""
        root = self._root
        if root is None or not self._items:
            return
        try:
            root.after(0, self._apply_state)
        except Exception:
            pass

    def stop(self) -> None:
        item, self._status_item = self._status_item, None
        if item is None:
            return

        def remove() -> None:
            try:
                import AppKit

                AppKit.NSStatusBar.systemStatusBar().removeStatusItem_(item)
            except Exception:
                pass

        try:
            if self._root is not None:
                self._root.after(0, remove)
            else:
                remove()
        except Exception:
            pass

    def _call(self, name: str) -> None:
        callback = self.callbacks.get(name)
        if callback:
            try:
                if name == "quit":
                    # Every quit names the place that asked (0.4.176): the tray's
                    # says source=tray, and on a Mac the menu bar is that place.
                    callback(source="menu_bar")
                else:
                    callback()
            except Exception:
                log.exception("menu bar action failed: %s", name)
