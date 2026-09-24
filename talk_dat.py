import multiprocessing as _multiprocessing

if __name__ == "__main__":
    # A frozen renderer child must divert before startup, URI handling or
    # audio imports can run a second dictation application.
    _multiprocessing.freeze_support()

import faulthandler as _faulthandler
import os as _os
import sys as _sys

try:
    # Resolve the data location before heavy imports, so native startup failures
    # are recorded in the same profile as settings and portable app data.
    _data_override = _os.environ.get("TALK_DAT_HOME")
    _portable_base = _os.path.dirname(_os.path.realpath(
        _sys.executable if getattr(_sys, "frozen", False) else _sys.argv[0]
    ))
    if _data_override:
        _crash_dir = _os.path.abspath(_os.path.expanduser(_data_override))
    elif _os.path.exists(_os.path.join(_portable_base, "portable.flag")):
        _crash_dir = _os.path.join(_portable_base, "TalkDatData")
    elif _sys.platform == "darwin":
        _crash_dir = _os.path.join(
            _os.path.expanduser("~/Library/Application Support"), "TalkDat"
        )
    else:
        _crash_dir = _os.path.join(
            _os.environ.get("APPDATA", _os.path.expanduser("~")), "TalkDat"
        )
    _os.makedirs(_crash_dir, mode=0o700, exist_ok=True)
    _crash_log = open(_os.path.join(_crash_dir, "crash-traceback.log"), "a", buffering=1)
    _faulthandler.enable(file=_crash_log)
except Exception:
    pass


if len(_sys.argv) > 1 and _sys.argv[1] == "--fire-permission-prompts":
    # A separate tiny process whose only job is to make macOS show its real
    # permission dialogs. The prompting APIs spin Cocoa's run loop inside the
    # call, which aborts the interpreter when done from inside the app's Tk
    # event loop -- that was the ask-three-times-then-vanish crash. Out here
    # there is no Tk, so nothing can be re-entered. In the bundled app this
    # process IS the app binary, so TCC attributes the request to Talk DAT!
    # and the grants register against the right bundle.
    try:
        try:
            import AVFoundation

            AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                AVFoundation.AVMediaTypeAudio, lambda granted: None
            )
        except Exception:
            pass
        try:
            from ApplicationServices import (
                AXIsProcessTrustedWithOptions,
                kAXTrustedCheckOptionPrompt,
            )
            from CoreFoundation import (
                CFDictionaryCreate,
                kCFBooleanTrue,
                kCFTypeDictionaryKeyCallBacks,
                kCFTypeDictionaryValueCallBacks,
            )

            options = CFDictionaryCreate(
                None, [kAXTrustedCheckOptionPrompt], [kCFBooleanTrue], 1,
                kCFTypeDictionaryKeyCallBacks, kCFTypeDictionaryValueCallBacks,
            )
            AXIsProcessTrustedWithOptions(options)
        except Exception:
            pass
        try:
            import ctypes
            import ctypes.util

            iokit = ctypes.CDLL(ctypes.util.find_library("IOKit"))
            request = iokit.IOHIDRequestAccess
            request.argtypes = [ctypes.c_uint32]
            request.restype = ctypes.c_bool
            request(1)  # kIOHIDRequestTypeListenEvent
        except Exception:
            pass
        # Stay alive while the dialogs are on screen so the requests are not
        # torn down mid-flight.
        from CoreFoundation import CFRunLoopRunInMode

        CFRunLoopRunInMode("kCFRunLoopDefaultMode", 20.0, False)
    except Exception:
        pass
    _sys.exit(0)

if len(_sys.argv) > 1 and str(_sys.argv[1]).startswith("talkdat:"):
    # X-11: launched by the browser. Hand the URI to the running app and
    # bow out; if nothing is running, the app starting now will claim it.
    from knight_flow.handoff import stash_uri_for_primary
    from knight_flow.single_instance import already_running

    stash_uri_for_primary(_sys.argv[1])
    if already_running():
        raise SystemExit(0)

from knight_flow.app import main


if __name__ == "__main__":
    main()
