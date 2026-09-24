"""The Pill's on-screen surface on macOS: a native NSWindow, not a Tk window.

Tk 9 on Aqua cannot draw the Pill. The full autopsy, every step measured
against window-server pixel captures:

- The ROOT window only sheds its title bar at a deiconify remap, and any
  remap permanently turns systemTransparent surfaces opaque black. Borderless
  and transparent are mutually exclusive on the root.
- A TOPLEVEL gets both -- but its painting is clipped to a lens: content
  vanishes toward the window's left and right edges no matter what is drawn
  (photo, label, or canvas vectors -- all three measured identically), and
  where art does not cover, Tk paints opaque black inside that lens. The
  shipped capsule frames rendered as a pointed sliver with black wings.
- Oversizing the window and killing the NSWindow shadow rescued the capsule
  but left the black lens painted around it. No Tk-level arrangement escapes
  it, because the black is Tk's own background flush under the same clip.

So the pixels bypass Tk entirely. This window is plain AppKit: borderless,
non-opaque, clear background, no shadow, floating level. Tk remains the brain
-- geometry decisions, state, menus, timers -- and mirrors every frame and
every move here. Mouse input lands on the native view and is queued back onto
the Tk thread through main_thread.post, the same discipline as every other
foreign-dispatch source in this app (NSWorkspace notifications, the Windows
WinEvent hook): the callback does nothing but enqueue.
"""

from __future__ import annotations

import io
import logging
from typing import Any, Callable

from . import main_thread
from .mac_support import IS_MAC

log = logging.getLogger(__name__)

_view_class: Any = None


def _pill_view_class():
    """The NSView subclass, defined once and lazily.

    Defining an Objective-C class twice raises "class already exists", and a
    module-level import-time definition would break every non-mac import of
    this module -- the same two constraints mac_menu_bar solved the same way.
    """
    global _view_class
    if _view_class is not None:
        return _view_class

    import objc
    from AppKit import NSImageView, NSTrackingArea

    class TalkDatPillView(NSImageView):
        def initWithHandler_(self, handler):
            self = objc.super(TalkDatPillView, self).init()
            if self is None:
                return None
            self._handler = handler
            self._tracking = None
            return self

        def updateTrackingAreas(self):
            objc.super(TalkDatPillView, self).updateTrackingAreas()
            if self._tracking is not None:
                self.removeTrackingArea_(self._tracking)
            # MouseEnteredAndExited | MouseMoved | ActiveAlways
            options = 0x01 | 0x02 | 0x80
            self._tracking = NSTrackingArea.alloc().initWithRect_options_owner_userInfo_(
                self.bounds(), options, self, None
            )
            self.addTrackingArea_(self._tracking)

        # Every event handler forwards ONE immutable description and returns.
        # Running overlay code here would be running Tk inside Cocoa's
        # dispatch, which is the crash class this app has already buried twice.
        @objc.python_method
        def _forward(self, kind, event):
            handler = self._handler
            if handler is None:
                return
            point = event.locationInWindow()
            frame = self.window().frame() if self.window() else None
            screen_x = frame.origin.x + point.x if frame else point.x
            # Cocoa's origin is bottom-left; the overlay thinks in Tk's
            # top-left coordinates, so flip against the primary screen.
            from AppKit import NSScreen

            screens = NSScreen.screens()
            primary_height = float(screens[0].frame().size.height) if screens else 0.0
            screen_y = primary_height - (frame.origin.y + point.y) if frame else point.y
            local_x = point.x
            local_y = (frame.size.height - point.y) if frame else point.y
            handler(kind, float(local_x), float(local_y), float(screen_x), float(screen_y))

        def mouseDown_(self, event):
            self._forward("press", event)

        def mouseDragged_(self, event):
            self._forward("drag", event)

        def mouseUp_(self, event):
            if int(event.clickCount()) >= 2:
                self._forward("double", event)
            self._forward("release", event)

        def rightMouseDown_(self, event):
            self._forward("context", event)

        def otherMouseDown_(self, event):
            self._forward("context", event)

        def mouseEntered_(self, event):
            self._forward("enter", event)

        def mouseExited_(self, event):
            self._forward("leave", event)

        def mouseMoved_(self, event):
            self._forward("motion", event)

        def acceptsFirstMouse_(self, _event):
            # The Pill must respond on the first click even when the app is
            # not frontmost -- it is an overlay, not a document window.
            return True

    _view_class = TalkDatPillView
    return _view_class


class NativePill:
    """A borderless, transparent, floating NSWindow that shows PIL frames."""

    def __init__(self, on_event: Callable[[str, float, float, float, float], None]) -> None:
        self.available = False
        self._window = None
        self._view = None
        self._on_event = on_event
        self._last_png: bytes | None = None
        if not IS_MAC:
            return
        try:
            from AppKit import (
                NSBackingStoreBuffered,
                NSColor,
                NSMakeRect,
                NSPanel,
                NSWindowCollectionBehaviorCanJoinAllSpaces,
                NSWindowCollectionBehaviorStationary,
            )

            # NSPanel with nonactivating style: clicking the Pill must not
            # yank focus away from the app the person is dictating into --
            # stealing focus would retarget the paste at the Pill itself.
            NONACTIVATING = 1 << 7
            panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 92, 26), NONACTIVATING, NSBackingStoreBuffered, False
            )
            panel.setOpaque_(False)
            panel.setBackgroundColor_(NSColor.clearColor())
            panel.setHasShadow_(False)
            panel.setLevel_(25)  # NSStatusWindowLevel: above normal and floating
            panel.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorStationary
            )
            panel.setHidesOnDeactivate_(False)
            panel.setMovable_(False)

            view = _pill_view_class().alloc().initWithHandler_(self._enqueue)
            panel.setContentView_(view)
            self._window = panel
            self._view = view
            self.available = True
        except Exception:
            log.exception("native pill window could not be created")

    # -- event plumbing ----------------------------------------------------
    def _enqueue(self, kind: str, x: float, y: float, sx: float, sy: float) -> None:
        callback = self._on_event
        if callback is None:
            return
        main_thread.post(lambda: callback(kind, x, y, sx, sy))

    # -- geometry ----------------------------------------------------------
    def set_frame(self, x: int, y: int, width: int, height: int) -> None:
        """Place the window, in Tk's top-left screen coordinates."""
        if not self.available:
            return
        try:
            from AppKit import NSMakeRect, NSScreen

            screens = NSScreen.screens()
            primary_height = float(screens[0].frame().size.height) if screens else 0.0
            cocoa_y = primary_height - y - height
            self._window.setFrame_display_(
                NSMakeRect(float(x), float(cocoa_y), float(width), float(height)), True
            )
        except Exception:
            log.debug("native pill set_frame failed", exc_info=True)

    def set_alpha(self, alpha: float) -> None:
        if not self.available:
            return
        try:
            self._window.setAlphaValue_(max(0.0, min(1.0, float(alpha))))
        except Exception:
            pass

    def show(self) -> None:
        if not self.available:
            return
        try:
            self._window.orderFrontRegardless()
        except Exception:
            pass

    def hide(self) -> None:
        if not self.available:
            return
        try:
            self._window.orderOut_(None)
        except Exception:
            pass

    def close(self) -> None:
        if not self.available:
            return
        try:
            self._window.orderOut_(None)
            self._window.close()
        except Exception:
            pass
        self.available = False

    # -- frames ------------------------------------------------------------
    def set_image(self, image) -> None:
        """Show a PIL image. Skips redundant uploads of the identical frame."""
        if not self.available or image is None:
            return
        try:
            from AppKit import NSData, NSImage

            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            png = buffer.getvalue()
            if png == self._last_png:
                return
            self._last_png = png
            data = NSData.dataWithBytes_length_(png, len(png))
            ns_image = NSImage.alloc().initWithData_(data)
            self._view.setImage_(ns_image)
        except Exception:
            log.debug("native pill set_image failed", exc_info=True)
