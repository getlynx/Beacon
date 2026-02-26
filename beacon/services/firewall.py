"""Firewall management service for Beacon.

Supports two backends:
- UFW  (ufw CLI)       — Debian / Ubuntu
- firewalld (firewall-cmd) — RedHat / CentOS / Fedora / Rocky / AlmaLinux

Backend is detected at runtime by checking which binary is available.
"""

from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List

# ---------------------------------------------------------------------------
# Port constants
# ---------------------------------------------------------------------------

LYNX_P2P_PORT = 22566

OPTIONAL_PORTS: list[dict] = [
    {"port": 9332, "label": "Lynx RPC", "proto": "TCP", "default": False},
]

_PREFS_FILE = Path.home() / ".beacon-firewall.json"
_SSHD_CONFIG = Path("/etc/ssh/sshd_config")


# ---------------------------------------------------------------------------
# SSH port detection (handles multiple Port directives + Include files)
# ---------------------------------------------------------------------------

def _parse_sshd_file(path: Path, visited: set[str]) -> list[int]:
    """Parse Port directives from a single sshd_config file, following Includes."""
    real = str(path.resolve())
    if real in visited:
        return []
    visited.add(real)

    ports: list[int] = []
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ports

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Follow Include directives
        m_inc = re.match(r"^[Ii]nclude\s+(.+)$", stripped)
        if m_inc:
            pattern = m_inc.group(1).strip()
            for inc_path in sorted(glob.glob(pattern)):
                ports.extend(_parse_sshd_file(Path(inc_path), visited))
            continue

        # Collect Port directives
        m_port = re.match(r"^[Pp]ort\s+(\d+)$", stripped)
        if m_port:
            ports.append(int(m_port.group(1)))

    return ports


def get_ssh_ports() -> list[int]:
    """Return all SSH listening ports from sshd_config (including Include files).

    Defaults to [22] if no Port directive is found.
    """
    visited: set[str] = set()
    ports = _parse_sshd_file(_SSHD_CONFIG, visited)
    seen: list[int] = []
    for p in ports:
        if p not in seen:
            seen.append(p)
    return seen if seen else [22]


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

def get_backend() -> str:
    """Return 'ufw', 'firewalld', or 'none' based on what is installed."""
    if shutil.which("ufw"):
        return "ufw"
    if shutil.which("firewall-cmd"):
        return "firewalld"
    return "none"


# ---------------------------------------------------------------------------
# Preferences persistence
# ---------------------------------------------------------------------------

def load_prefs() -> dict:
    """Load firewall preferences from ~/.beacon-firewall.json."""
    try:
        if _PREFS_FILE.exists():
            return json.loads(_PREFS_FILE.read_text())
    except Exception:
        pass
    return {"optional_ports": {}}


def save_prefs(prefs: dict) -> None:
    """Persist firewall preferences to ~/.beacon-firewall.json."""
    try:
        _PREFS_FILE.write_text(json.dumps(prefs, indent=2))
    except Exception:
        pass


def get_optional_port_enabled(port: int) -> bool:
    """Return whether an optional port is currently enabled in prefs."""
    prefs = load_prefs()
    opt_map = prefs.get("optional_ports", {})
    # Default from OPTIONAL_PORTS definition if not yet saved
    default = next(
        (p["default"] for p in OPTIONAL_PORTS if p["port"] == port), False
    )
    return opt_map.get(str(port), default)


def set_optional_port_pref(port: int, enabled: bool) -> None:
    """Persist an optional port preference."""
    prefs = load_prefs()
    prefs.setdefault("optional_ports", {})[str(port)] = enabled
    save_prefs(prefs)


def get_enabled_optional_ports() -> list[int]:
    """Return list of optional port numbers that are currently enabled."""
    return [
        p["port"] for p in OPTIONAL_PORTS if get_optional_port_enabled(p["port"])
    ]


# ---------------------------------------------------------------------------
# UFW backend
# ---------------------------------------------------------------------------

def _run(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=30, check=check
    )


def _ufw_status() -> str:
    """Return 'active', 'inactive', or 'unavailable'."""
    try:
        r = _run(["ufw", "status"])
        if "Status: active" in r.stdout:
            return "active"
        return "inactive"
    except Exception:
        return "unavailable"


def _ufw_has_existing_rules() -> bool:
    """Return True if UFW already has non-default rules configured."""
    try:
        r = _run(["ufw", "status", "verbose"])
        lines = r.stdout.splitlines()
        # Look for any rule lines (they appear after the "Rules:" header)
        in_rules = False
        for line in lines:
            if line.strip().lower().startswith("rules:"):
                in_rules = True
                continue
            if in_rules and line.strip() and not line.startswith("-"):
                return True
        return False
    except Exception:
        return False


def _ufw_ensure_ipv6() -> None:
    """Ensure /etc/default/ufw has IPV6=yes for dual-stack coverage."""
    ufw_defaults = Path("/etc/default/ufw")
    if not ufw_defaults.exists():
        return
    text = ufw_defaults.read_text()
    if re.search(r"^IPV6\s*=\s*yes", text, re.MULTILINE):
        return
    # Patch IPV6=no or missing to IPV6=yes
    if re.search(r"^IPV6\s*=", text, re.MULTILINE):
        text = re.sub(r"^(IPV6\s*=\s*).*$", r"\1yes", text, flags=re.MULTILINE)
    else:
        text += "\nIPV6=yes\n"
    ufw_defaults.write_text(text)


def _ufw_enable(ssh_ports: list[int], optional_ports: list[int]) -> tuple[bool, str]:
    """Configure and enable UFW with deny-all + allowed ports."""
    try:
        _ufw_ensure_ipv6()
        _run(["ufw", "--force", "reset"])
        _run(["ufw", "default", "deny", "incoming"], check=True)
        _run(["ufw", "default", "allow", "outgoing"], check=True)
        for port in ssh_ports:
            _run(["ufw", "allow", f"{port}/tcp"], check=True)
        _run(["ufw", "allow", f"{LYNX_P2P_PORT}/tcp"], check=True)
        for port in optional_ports:
            _run(["ufw", "allow", f"{port}/tcp"], check=True)
        _run(["ufw", "--force", "enable"], check=True)
        return True, "Firewall enabled."
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip() or str(e)
    except Exception as e:
        return False, str(e)


def _ufw_disable() -> tuple[bool, str]:
    try:
        _run(["ufw", "--force", "disable"], check=True)
        return True, "Firewall disabled."
    except Exception as e:
        return False, str(e)


def _ufw_set_port(port: int, enabled: bool) -> tuple[bool, str]:
    try:
        if enabled:
            _run(["ufw", "allow", f"{port}/tcp"], check=True)
        else:
            _run(["ufw", "delete", "allow", f"{port}/tcp"], check=True)
        return True, ""
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# firewalld backend
# ---------------------------------------------------------------------------

def _firewalld_status() -> str:
    try:
        r = _run(["firewall-cmd", "--state"])
        if r.returncode == 0 and "running" in r.stdout.lower():
            return "active"
        return "inactive"
    except Exception:
        return "unavailable"


def _firewalld_has_existing_rules() -> bool:
    """Return True if firewalld drop zone already has non-default port rules."""
    try:
        r = _run(["firewall-cmd", "--permanent", "--zone=drop", "--list-ports"])
        ports = r.stdout.strip()
        return bool(ports)
    except Exception:
        return False


def _firewalld_get_active_interface() -> str | None:
    """Return the first active network interface name."""
    try:
        r = _run(["firewall-cmd", "--get-active-zones"])
        # Output format: zone\n  interfaces: eth0 eth1\n
        lines = r.stdout.splitlines()
        for i, line in enumerate(lines):
            if "interfaces:" in line:
                ifaces = line.split("interfaces:")[-1].strip().split()
                if ifaces:
                    return ifaces[0]
    except Exception:
        pass
    return None


def _firewalld_enable(ssh_ports: list[int], optional_ports: list[int]) -> tuple[bool, str]:
    try:
        _run(["systemctl", "start", "firewalld"], check=True)
        _run(["systemctl", "enable", "firewalld"], check=True)

        # Set default zone to drop (deny all inbound)
        _run(["firewall-cmd", "--permanent", "--set-default-zone=drop"], check=True)

        # Move active interface to drop zone explicitly to override any existing zone binding
        iface = _firewalld_get_active_interface()
        if iface:
            _run([
                "firewall-cmd", "--permanent", "--zone=drop",
                f"--change-interface={iface}"
            ])

        # Remove all existing ports from drop zone first (clean slate)
        r = _run(["firewall-cmd", "--permanent", "--zone=drop", "--list-ports"])
        for existing in r.stdout.strip().split():
            _run(["firewall-cmd", "--permanent", "--zone=drop", f"--remove-port={existing}"])

        # Add required ports
        for port in ssh_ports:
            _run(["firewall-cmd", "--permanent", "--zone=drop", f"--add-port={port}/tcp"], check=True)
        _run(["firewall-cmd", "--permanent", "--zone=drop", f"--add-port={LYNX_P2P_PORT}/tcp"], check=True)
        for port in optional_ports:
            _run(["firewall-cmd", "--permanent", "--zone=drop", f"--add-port={port}/tcp"], check=True)

        _run(["firewall-cmd", "--reload"], check=True)
        return True, "Firewall enabled."
    except subprocess.CalledProcessError as e:
        return False, e.stderr.strip() or str(e)
    except Exception as e:
        return False, str(e)


def _firewalld_disable() -> tuple[bool, str]:
    try:
        _run(["systemctl", "disable", "--now", "firewalld"], check=True)
        return True, "Firewall disabled."
    except Exception as e:
        return False, str(e)


def _firewalld_set_port(port: int, enabled: bool) -> tuple[bool, str]:
    try:
        action = "--add-port" if enabled else "--remove-port"
        _run([
            "firewall-cmd", "--permanent", "--zone=drop",
            f"{action}={port}/tcp"
        ], check=True)
        _run(["firewall-cmd", "--reload"], check=True)
        return True, ""
    except Exception as e:
        return False, str(e)


# ---------------------------------------------------------------------------
# Public API (backend-agnostic)
# ---------------------------------------------------------------------------

def get_status() -> str:
    """Return 'active', 'inactive', or 'unavailable'."""
    backend = get_backend()
    if backend == "ufw":
        return _ufw_status()
    if backend == "firewalld":
        return _firewalld_status()
    return "unavailable"


def get_has_existing_rules() -> bool:
    """Return True if the firewall backend already has custom rules that would be reset."""
    backend = get_backend()
    if backend == "ufw":
        return _ufw_has_existing_rules()
    if backend == "firewalld":
        return _firewalld_has_existing_rules()
    return False


def enable_firewall() -> tuple[bool, str]:
    """Enable the firewall with deny-all inbound + SSH + Lynx P2P + enabled optional ports."""
    backend = get_backend()
    ssh_ports = get_ssh_ports()
    optional = get_enabled_optional_ports()
    if backend == "ufw":
        return _ufw_enable(ssh_ports, optional)
    if backend == "firewalld":
        return _firewalld_enable(ssh_ports, optional)
    return False, "No firewall backend available."


def disable_firewall() -> tuple[bool, str]:
    """Disable the firewall entirely."""
    backend = get_backend()
    if backend == "ufw":
        return _ufw_disable()
    if backend == "firewalld":
        return _firewalld_disable()
    return False, "No firewall backend available."


def set_optional_port(port: int, enabled: bool) -> tuple[bool, str]:
    """Enable or disable an optional port. Updates prefs and live rules if firewall is active."""
    set_optional_port_pref(port, enabled)
    if get_status() != "active":
        return True, ""
    backend = get_backend()
    if backend == "ufw":
        return _ufw_set_port(port, enabled)
    if backend == "firewalld":
        return _firewalld_set_port(port, enabled)
    return False, "No firewall backend available."
