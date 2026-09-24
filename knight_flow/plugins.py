"""Opt-in trusted Python text extensions, isolated from the dictation process.

A private subprocess bounds accidental crashes and stalls. It does not restrict
a trusted plugin's filesystem, network or subprocess access.
"""

from __future__ import annotations
import atexit, json, multiprocessing, queue, threading, time
from .config import app_dir
from .plugin_worker import PluginAPI, MAX_MESSAGE, MAX_TEXT, main as _run_host

CALL_SECONDS = 0.35
LOAD_SECONDS = 1.0
TOTAL_LOAD_SECONDS = 2.0
FILTER_BATCH_SECONDS = 0.5
_lock = threading.RLock()
_api = None
_home = None
_hosts = []
_load_errors = []


def plugins_dir():
    path = app_dir() / "plugins"
    path.mkdir(parents=True, exist_ok=True)
    return path


def plugins_enabled(config):
    value = config.get("plugins", {})
    return type(value) is dict and value.get("enabled") is True


def load_errors():
    with _lock:
        return list(_load_errors)


def _error(name, kind):
    # Exception messages can contain dictated text or private config.
    if (
        type(kind) is not str
        or len(kind) > 80
        or not kind.replace("_", "").isascii()
        or not kind.replace("_", "").isalnum()
    ):
        kind = "Failed"
    message = f"{name[:120]}: {kind}"
    with _lock:
        if message not in _load_errors:
            _load_errors.append(message)
        del _load_errors[:-128]


class _Host:
    def __init__(self, path, timeout):
        self.path = path
        self.process = None
        self.lock = threading.Lock()
        self.responses = queue.Queue(maxsize=1)
        self.closed = False
        context = multiprocessing.get_context("spawn")
        self.connection, child = context.Pipe(duplex=True)
        self.process = context.Process(
            target=_run_host, args=(child, str(path)), name="TalkDatPlugin", daemon=True
        )
        try:
            self.process.start()
        except Exception:
            self.connection.close()
            child.close()
            raise
        child.close()

        def read():
            try:
                while not self.closed:
                    raw = self.connection.recv_bytes(MAX_MESSAGE)
                    value = json.loads(raw)
                    if type(value) is not dict:
                        raise ValueError("Invalid reply")
                    self.responses.put_nowait(value)
            except Exception:
                try:
                    self.responses.put_nowait({"ok": False, "error": "HostClosed"})
                except queue.Full:
                    pass

        try:
            threading.Thread(
                target=read, name="TalkDatPluginReplies", daemon=True
            ).start()
        except Exception:
            self.close()
            raise
        try:
            self.info = self.responses.get(timeout=timeout)
        except queue.Empty:
            self.close()
            raise TimeoutError
        if self.info.get("ok") is not True:
            kind = self.info.get("error", "LoadFailed")
            self.close()
            raise RuntimeError(str(kind))
        keys = self.info.get("transforms")
        count = self.info.get("filters")
        if (
            not isinstance(keys, list)
            or len(keys) > 128
            or any(type(k) is not str or len(k) > 80 for k in keys)
            or type(count) is not int
            or not 0 <= count <= 128
        ):
            self.close()
            raise ValueError("Invalid registration")

    def close(self):
        if self.closed:
            return
        self.closed = True
        process = self.process
        if process is None:
            return
        if process.is_alive():
            try:
                process.kill()
            except OSError:
                pass
        try:
            process.join(timeout=0.2)
        except OSError:
            pass

        # A plugin's own child may inherit its pipe. Closing that stream from
        # this caller can block on the reader's I/O lock even after our host
        # has died. Resource cleanup must also respect the dictation deadline.
        def close_pipes():
            try:
                self.connection.close()
            except OSError:
                pass
            if not process.is_alive():
                process.close()

        threading.Thread(
            target=close_pipes, name="TalkDatPluginPipeClose", daemon=True
        ).start()

    def call(self, op, key, text, config, *, timeout=CALL_SECONDS):
        if self.closed or type(text) is not str or len(text) > MAX_TEXT:
            return None
        deadline = time.monotonic() + min(CALL_SECONDS, max(0, timeout))
        if not self.lock.acquire(timeout=max(0, deadline - time.monotonic())):
            _error(self.path.name, "Busy")
            return None
        try:
            try:
                raw = json.dumps(
                    {"op": op, "key": key, "text": text, "config": config},
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode("utf-8")
            except (ValueError, TypeError, UnicodeError):
                _error(self.path.name, "InvalidInput")
                return None
            if len(raw) > MAX_MESSAGE:
                _error(self.path.name, "InputTooLarge")
                return None

            def write():
                try:
                    self.connection.send_bytes(raw)
                except (OSError, ValueError):
                    try:
                        self.responses.put_nowait({"ok": False, "error": "HostClosed"})
                    except queue.Full:
                        pass

            threading.Thread(
                target=write, name="TalkDatPluginRequest", daemon=True
            ).start()
            try:
                result = self.responses.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                self.close()
                _error(self.path.name, "TimedOut")
                return None
            if result.get("ok") is not True:
                kind = result.get("error", "Failed")
                if kind == "HostClosed":
                    self.close()
                _error(
                    self.path.name,
                    kind if type(kind) is str and len(kind) < 80 else "Failed",
                )
                return None
            result = result.get("text")
            if type(result) is not str or not result.strip() or len(result) > MAX_TEXT:
                _error(self.path.name, "InvalidOutput")
                return None
            return result
        finally:
            self.lock.release()


def _load_all():
    global _api, _home
    with _lock:
        home = plugins_dir().resolve()
        if _api is not None and home == _home:
            return _api
        reload_plugins()
        _home = home
        api = PluginAPI()
        deadline = time.monotonic() + TOTAL_LOAD_SECONDS
        for index, path in enumerate(sorted(home.glob("*.py"))):
            remaining = deadline - time.monotonic()
            if index >= 32 or remaining <= 0:
                _error(path.name, "LoadLimit")
                break
            try:
                host = _Host(path, min(LOAD_SECONDS, remaining))
                _hosts.append(host)
                for key in host.info["transforms"]:
                    api.transforms[key] = lambda text, config, h=host, k=key: h.call(
                        "transform", k, text, config
                    )
                for key in range(host.info["filters"]):
                    api.text_filters.append((host, key))
            except Exception as error:
                kind = (
                    str(error)
                    if isinstance(error, RuntimeError)
                    else type(error).__name__
                )
                _error(path.name, kind)
        _api = api
        return api


def reload_plugins():
    global _api, _home
    with _lock:
        for host in _hosts:
            host.close()
        _hosts.clear()
        _load_errors.clear()
        _api = None
        _home = None


def plugin_transform(transform_id, text, config):
    if not plugins_enabled(config):
        return None
    try:
        fn = _load_all().transforms.get(transform_id)
    except Exception as error:
        _error("Plugins", type(error).__name__)
        return None
    result = fn(text, config) if fn else None
    if result is not None:
        from .formatting import strip_em_dashes

        result = strip_em_dashes(result)
    return result


def plugin_text_filters(config):
    if not plugins_enabled(config):
        return []
    callbacks = []
    batch = threading.local()
    try:
        registered = list(_load_all().text_filters)
    except Exception as error:
        _error("Plugins", type(error).__name__)
        return []
    for index, (host, key) in enumerate(registered):

        def apply(text, config, h=host, k=key, first=index == 0):
            if first or not hasattr(batch, "deadline"):
                batch.deadline = time.monotonic() + FILTER_BATCH_SECONDS
            remaining = batch.deadline - time.monotonic()
            if remaining <= 0:
                _error(h.path.name, "RunLimit")
                return text
            result = h.call("filter", k, text, config, timeout=remaining)
            if result is None:
                return text
            from .formatting import strip_em_dashes

            return strip_em_dashes(result)

        callbacks.append(apply)
    return callbacks


atexit.register(reload_plugins)

_job_lock = threading.Lock()
_reload_done = threading.Event()
_reload_done.set()
_reload_generation = 0
_reload_config = None


def request_reload(config=None):
    """Reload only the latest request, away from the UI and capture threads."""
    global _reload_generation, _reload_config
    import copy

    with _job_lock:
        _reload_generation += 1
        _reload_config = copy.deepcopy(config)
        if config is None and _reload_done.is_set() and not _hosts and _api is None:
            return _reload_done
        if not _reload_done.is_set():
            return _reload_done
        _reload_done.clear()

    def work():
        while True:
            with _job_lock:
                generation = _reload_generation
                wanted = _reload_config
            try:
                reload_plugins()
                if wanted is not None and plugins_enabled(wanted):
                    _load_all()
            except Exception as error:
                _error("Plugins", type(error).__name__)
            with _job_lock:
                if generation == _reload_generation:
                    _reload_done.set()
                    return

    try:
        threading.Thread(target=work, name="TalkDatPluginReload", daemon=True).start()
    except Exception:
        _reload_done.set()
        _error("Plugins", "ReloadFailed")
    return _reload_done


def snapshot(config):
    """Read status without loading code or waiting for a busy import."""
    enabled = plugins_enabled(config)
    if not _reload_done.is_set():
        return {
            "phase": "loading",
            "message": "Updating installed plugins...",
            "errors": [],
        }
    if not enabled:
        return {"phase": "disabled", "message": "Plugins are off.", "errors": []}
    if not _lock.acquire(blocking=False):
        return {
            "phase": "loading",
            "message": "Loading installed plugins...",
            "errors": [],
        }
    try:
        if _api is None:
            return {
                "phase": "unloaded",
                "message": "Plugins have not been loaded.",
                "errors": list(_load_errors),
            }
        errors = list(_load_errors)
        return {
            "phase": "warning" if errors else "ready",
            "message": f"Loaded plugin files: {len(_hosts)}. Reported issues: {len(errors)}."
            if errors
            else f"{len(_hosts)} plugin files loaded.",
            "errors": errors,
            "transforms": len(_api.transforms),
            "filters": len(_api.text_filters),
        }
    finally:
        _lock.release()
