import os
import sys
import contextlib



class _TraceStream:
    """Proxy stream that mirrors writes and logs call-site context to the journal."""

    def __init__(self, name: str, wrapped, self_file: str, extract_stack) -> None:
        self._name = name
        self._wrapped = wrapped
        self._self_file = self_file
        self._extract_stack = extract_stack

    def write(self, data) -> int:
        text = data if isinstance(data, str) else str(data)
        written = self._wrapped.write(text)
        if text and text.strip():
            caller = "unknown"
            for frame in reversed(self._extract_stack(limit=16)[:-1]):
                if frame.filename != self._self_file:
                    caller = f"{frame.filename}:{frame.lineno}:{frame.name}"
                    break
            escaped = text.replace("\n", "\\n")
            from beacon.journal import debug
            debug(f"trace {self._name} {caller} {escaped!r}")
        return written

    def flush(self) -> None:
        self._wrapped.flush()

    def isatty(self) -> bool:
        return self._wrapped.isatty()

    def fileno(self) -> int:
        return self._wrapped.fileno()

    def __getattr__(self, name: str):
        return getattr(self._wrapped, name)


def _enable_startup_trace():
    """Enable optional startup output tracing via BEACON_TRACE_STARTUP=1."""
    if os.environ.get("BEACON_TRACE_STARTUP") != "1":
        return None
    # Import only when tracing is enabled to keep normal startup lean.
    from traceback import extract_stack
    from beacon.journal import info

    info(f"startup trace enabled pid={os.getpid()}")
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    self_file = __file__
    sys.stdout = _TraceStream("stdout", original_stdout, self_file, extract_stack)
    sys.stderr = _TraceStream("stderr", original_stderr, self_file, extract_stack)

    def _restore() -> None:
        sys.stdout = original_stdout
        sys.stderr = original_stderr

    return _restore


@contextlib.contextmanager
def _suppress_fds_during_import() -> None:
    """Suppress low-level fd writes (stdout/stderr) during import-time only."""
    stdout_fd = sys.stdout.fileno()
    stderr_fd = sys.stderr.fileno()
    saved_stdout = os.dup(stdout_fd)
    saved_stderr = os.dup(stderr_fd)
    devnull_fd = os.open(os.devnull, os.O_WRONLY)
    try:
        os.dup2(devnull_fd, stdout_fd)
        os.dup2(devnull_fd, stderr_fd)
        yield
    finally:
        os.dup2(saved_stdout, stdout_fd)
        os.dup2(saved_stderr, stderr_fd)
        os.close(saved_stdout)
        os.close(saved_stderr)
        os.close(devnull_fd)



def _apply_terminal_compatibility_patches() -> None:
    """Avoid terminal capability probes that can leak visible chars on some clients.

    On macOS Terminal over SSH, Textual's capability queries (ending in ``$p``)
    can briefly render literal ``p`` characters before full-screen mode is
    active.
    """
    # Safe default: disable these probes unless explicitly re-enabled.
    if os.environ.get("BEACON_ENABLE_TERMINAL_QUERIES") == "1":
        return
    try:
        from textual.drivers.linux_driver import LinuxDriver
    except Exception:
        return

    def _noop(self) -> None:
        return

    LinuxDriver._request_terminal_sync_mode_support = _noop
    LinuxDriver._query_in_band_window_resize = _noop


def _import_and_run_app(trace_enabled: bool) -> None:
    """Import and run Beacon app with startup-safe output handling."""
    if trace_enabled:
        from beacon.app import run
        run()
        return

    # Suppress import-time output from Python and native side effects.
    with _suppress_fds_during_import():
        from beacon.app import run
    run()


def _maybe_restart_after_update() -> None:
    """If update just completed, replace this process with the updated Beacon."""
    if os.environ.pop("BEACON_RESTART_AFTER_EXIT", None) != "1":
        return
    venv_python = "/usr/local/beacon/venv/bin/python"
    if not os.path.isfile(venv_python):
        return
    os.execv(venv_python, [venv_python, "-m", "beacon"])


if __name__ == "__main__":
    trace_enabled = os.environ.get("BEACON_TRACE_STARTUP") == "1"
    _restore_trace = _enable_startup_trace()
    try:
        _apply_terminal_compatibility_patches()
        _import_and_run_app(trace_enabled=trace_enabled)
        _maybe_restart_after_update()
    except ModuleNotFoundError as e:
        if "textual" in str(e) or "pyproj" in str(e):
            print("Missing dependency. Run from project root: python3 run", file=sys.stderr)
            print("  (or: ./run)", file=sys.stderr)
            sys.exit(1)
        raise
    finally:
        if _restore_trace:
            _restore_trace()
