import os
import shutil
import sys
import time
import textwrap
import contextlib

SPLASH_TEXT = (
    "In an era where digital information faces constant threats of loss, "
    "manipulation, or obsolescence, Lynx Data Storage technology offers a "
    "groundbreaking solution for permanent data storage.\n\n"
    "Running Beacon helps advance this mission. Thank you for being part of it.\n\n"
    "Read more at https://docs.getlynx.io/"
)
SPLASH_LOGO = [
    "██╗  ██╗   ██╗███╗   ██╗██╗  ██╗",
    "██║  ╚██╗ ██╔╝████╗  ██║╚██╗██╔╝",
    "██║   ╚████╔╝ ██╔██╗ ██║ ╚███╔╝ ",
    "██║    ╚██╔╝  ██║╚██╗██║ ██╔██╗ ",
    "███████╗██║   ██║ ╚████║██╔╝ ██╗",
    "╚══════╝╚═╝   ╚═╝  ╚═══╝╚═╝  ╚═╝",
]


class _TraceStream:
    """Proxy stream that mirrors writes and logs call-site context."""

    def __init__(self, name: str, wrapped, log_file, self_file: str, extract_stack) -> None:
        self._name = name
        self._wrapped = wrapped
        self._log = log_file
        self._self_file = self_file
        self._extract_stack = extract_stack

    def write(self, data) -> int:
        text = data if isinstance(data, str) else str(data)
        written = self._wrapped.write(text)
        if text:
            caller = "unknown"
            for frame in reversed(self._extract_stack(limit=16)[:-1]):
                if frame.filename != self._self_file:
                    caller = f"{frame.filename}:{frame.lineno}:{frame.name}"
                    break
            escaped = text.replace("\n", "\\n")
            self._log.write(f"{time.time():.6f} {self._name} {caller} {escaped!r}\n")
            self._log.flush()
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
        return None, None
    # Import only when tracing is enabled to keep normal startup lean.
    from traceback import extract_stack

    trace_path = os.environ.get(
        "BEACON_STARTUP_TRACE_FILE",
        f"/tmp/beacon-startup-trace-{os.getpid()}.log",
    )
    log_file = open(trace_path, "a", encoding="utf-8")
    log_file.write(f"\n--- startup trace pid={os.getpid()} ts={time.time():.6f} ---\n")
    log_file.flush()
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    self_file = __file__
    sys.stdout = _TraceStream("stdout", original_stdout, log_file, self_file, extract_stack)
    sys.stderr = _TraceStream("stderr", original_stderr, log_file, self_file, extract_stack)

    def _restore() -> None:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        log_file.close()

    return _restore, trace_path


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


def _show_startup_splash() -> None:
    if os.environ.get("BEACON_NO_SPLASH") == "1":
        return
    if not (sys.stdout.isatty() and sys.stdin.isatty()):
        return
    columns, rows = shutil.get_terminal_size((100, 30))
    inner_width = max(44, min(columns - 8, 72))
    wrap_width = max(20, inner_width - 4)
    wrapped: list[str] = []
    paragraphs = SPLASH_TEXT.split("\n\n")
    for idx, paragraph in enumerate(paragraphs):
        para = paragraph.strip()
        if para:
            wrapped.extend(textwrap.wrap(para, width=wrap_width))
        else:
            wrapped.append("")
        if idx < len(paragraphs) - 1:
            wrapped.append("")
    content_lines = SPLASH_LOGO + [""] + wrapped
    box_width = min(columns - 2, max(len(line) for line in content_lines) + 4)
    box_width = max(24, box_width)
    box_height = len(content_lines) + 2
    total_lines = box_height + 2  # top/bottom border + content
    top_pad = max(0, (rows - total_lines) // 2)
    left_pad = max(0, (columns - box_width) // 2)
    indent = " " * left_pad

    # Rainbow ANSI color palette — ends on green (Lynx brand)
    RESET = "\x1b[0m"
    RAINBOW = [
        "\x1b[38;5;196m",  # red
        "\x1b[38;5;202m",  # orange
        "\x1b[38;5;226m",  # yellow
        "\x1b[38;5;46m",   # bright green
        "\x1b[38;5;51m",   # cyan
        "\x1b[38;5;21m",   # blue
        "\x1b[38;5;129m",  # violet
        "\x1b[38;5;201m",  # magenta
    ]
    GREEN = "\x1b[38;5;46m"

    def _render_frame(logo_colors: list[str], dim_rest: bool = False) -> None:
        sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.write("\n" * top_pad)
        sys.stdout.write(f"{indent}{' ' * box_width}\n")
        for i, line in enumerate(content_lines):
            if i < len(SPLASH_LOGO):
                color = logo_colors[i % len(logo_colors)]
                sys.stdout.write(f"{indent}  {color}{line:<{box_width - 4}}{RESET}\n")
            else:
                dimmed = "\x1b[2m" if dim_rest else ""
                sys.stdout.write(f"{indent}  {dimmed}{line:<{box_width - 4}}{RESET}\n")
        sys.stdout.write(f"{indent}{' ' * box_width}\n")
        sys.stdout.flush()

    # Animate: cycle rainbow colors across logo lines for ~1.8s (18 frames @ 100ms)
    num_logo_lines = len(SPLASH_LOGO)
    frames = 18
    for frame in range(frames):
        colors = [RAINBOW[(frame + i) % len(RAINBOW)] for i in range(num_logo_lines)]
        _render_frame(colors, dim_rest=True)
        time.sleep(0.1)

    # Final frame: all green, text at full brightness
    _render_frame([GREEN] * num_logo_lines, dim_rest=False)
    time.sleep(1.2)
    # Intentionally do not clear here; let Textual take over immediately.


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


def _import_and_run_app(trace_enabled: bool, trace_path: str | None) -> None:
    """Import and run Beacon app with startup-safe output handling."""
    if trace_enabled:
        from beacon.app import run
        if trace_path:
            try:
                sys.stderr.write(f"Startup trace enabled: {trace_path}\n")
            except Exception:
                pass
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
    _restore_trace, _trace_path = _enable_startup_trace()
    try:
        _show_startup_splash()
        _apply_terminal_compatibility_patches()
        _import_and_run_app(trace_enabled=trace_enabled, trace_path=_trace_path)
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
