"""Backup service for Lynx wallet backups."""

import hashlib
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from beacon.services.rpc import RpcClient


def get_rpc() -> RpcClient:
    return RpcClient()


def get_backup_dir(rpc: RpcClient | None = None) -> str:
    """Return the backup directory path."""
    return (rpc or get_rpc()).get_backup_dir()


def run_manual_backup(rpc: RpcClient | None = None) -> tuple[bool, str]:
    """Run a manual backup. Applies hash dedup. Returns (success, filename_or_error)."""
    rpc = rpc or get_rpc()
    backup_dir = rpc.get_backup_dir()
    datadir = rpc.get_datadir()
    chain_id = "lynx"
    Path(backup_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
    dest = os.path.join(backup_dir, f"{ts}-{chain_id}.dat")
    ok, msg = rpc.backupwallet(dest)
    if not ok:
        return False, msg
    try:
        with open(dest, "rb") as f:
            new_hash = hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return True, os.path.basename(dest)
    last_hash_file = os.path.join(backup_dir, ".last-hash")
    if os.path.isfile(last_hash_file):
        with open(last_hash_file) as f:
            old_hash = f.read().strip()
        if new_hash == old_hash:
            try:
                os.remove(dest)
            except OSError:
                pass
            return True, "(unchanged, skipped)"
    with open(last_hash_file, "w") as f:
        f.write(new_hash)
    return True, os.path.basename(dest)


def get_backup_list(rpc: RpcClient | None = None) -> list[dict[str, Any]]:
    """Return list of backups sorted by mtime desc."""
    rpc = rpc or get_rpc()
    return rpc.list_backups()


def get_timer_status() -> tuple[str, str]:
    """Return (is_active, next_run_str)."""
    try:
        r = subprocess.run(
            ["systemctl", "is-active", "lynx-backup.timer"],
            check=False,
            capture_output=True,
            text=True,
        )
        active = (r.stdout or "").strip() or "unknown"
    except Exception:
        active = "unknown"
    next_run = ""
    try:
        r = subprocess.run(
            ["systemctl", "list-timers", "lynx-backup.timer", "--no-legend", "--no-pager"],
            check=False,
            capture_output=True,
            text=True,
        )
        if r.returncode == 0 and r.stdout:
            parts = r.stdout.strip().split()
            if len(parts) >= 3:
                next_run = f"{parts[0]} {parts[1]} {parts[2]}"
    except Exception:
        pass
    return active, next_run


def prune_old_backups(rpc: RpcClient | None = None) -> int:
    """Delete backups older than 90 days. Return count deleted."""
    rpc = rpc or get_rpc()
    backup_dir = Path(rpc.get_backup_dir())
    if not backup_dir.is_dir():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    cutoff_ts = cutoff.timestamp()
    deleted = 0
    for f in backup_dir.glob("*.dat"):
        try:
            if f.stat().st_mtime < cutoff_ts:
                f.unlink()
                deleted += 1
        except OSError:
            continue
    return deleted
