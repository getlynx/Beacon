"""ElectrumX service detection and control for Beacon."""

import subprocess
from pathlib import Path

ELECTRUMX_CONF_PATH = "/etc/electrumx.conf"
ELECTRUMX_UNIT = "electrumx.service"


def is_electrumx_installed() -> bool:
    """Return True if ElectrumX is installed (systemd unit or config present)."""
    if Path(ELECTRUMX_CONF_PATH).exists():
        return True
    try:
        result = subprocess.run(
            ["systemctl", "list-unit-files", ELECTRUMX_UNIT, "--no-pager", "--no-legend"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and ELECTRUMX_UNIT in (result.stdout or ""):
            return True
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return False


def get_electrumx_conf_path() -> str:
    """Return path to ElectrumX config (e.g. /etc/electrumx.conf)."""
    return ELECTRUMX_CONF_PATH


def get_electrumx_status() -> str:
    """Return systemd active state: 'active', 'inactive', or 'unknown'."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", ELECTRUMX_UNIT],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip() or "unknown"
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return "unknown"


def start_electrumx() -> tuple[bool, str]:
    """Start electrumx.service. Returns (success, message)."""
    try:
        result = subprocess.run(
            ["systemctl", "start", ELECTRUMX_UNIT],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
    except Exception as exc:
        return False, str(exc)


def stop_electrumx() -> tuple[bool, str]:
    """Stop electrumx.service. Returns (success, message)."""
    try:
        result = subprocess.run(
            ["systemctl", "stop", ELECTRUMX_UNIT],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
    except Exception as exc:
        return False, str(exc)


def get_electrumx_journal_lines(n: int = 30) -> list[str]:
    """Return last n lines from journalctl -u electrumx for display in ElectrumXLogCard.
    Uses -o short-precise so output matches journalctl -f -u electrumx -n N (timestamp + unit + message)."""
    if n <= 0:
        return []
    try:
        result = subprocess.run(
            ["journalctl", "-u", "electrumx", "-n", str(n), "--no-pager", "-o", "short-precise"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.rstrip("\n").splitlines()
        if result.returncode != 0 and result.stderr:
            return [f"journalctl error: {result.stderr.strip()[:200]}"]
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        return [f"journalctl error: {exc!s}"[:200]]
    return ["No ElectrumX journal entries."]
