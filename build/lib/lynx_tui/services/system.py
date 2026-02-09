import os
import subprocess
from pathlib import Path
from typing import Tuple


class SystemClient:
    def get_timezone(self) -> str:
        try:
            result = subprocess.run(
                ["timedatectl", "show", "-p", "Timezone", "--value"],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            return "unknown"
        if result.returncode != 0:
            return "unknown"
        return (result.stdout or "").strip() or "unknown"

    def list_timezones(self) -> list[str]:
        try:
            result = subprocess.run(
                ["timedatectl", "list-timezones"],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            result = None
        if result and result.returncode == 0:
            return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        zoneinfo_root = Path("/usr/share/zoneinfo")
        if not zoneinfo_root.exists():
            return []
        timezones: list[str] = []
        for root, dirs, files in os.walk(zoneinfo_root):
            rel_root = os.path.relpath(root, zoneinfo_root)
            if rel_root.startswith("posix") or rel_root.startswith("right"):
                continue
            for name in files:
                if name in {"localtime", "posixrules", "Factory"}:
                    continue
                rel_path = os.path.normpath(os.path.join(rel_root, name))
                if rel_path.startswith("."):
                    continue
                timezones.append(rel_path)
        return sorted(set(timezones))

    def set_timezone(self, timezone: str) -> Tuple[bool, str]:
        timezone = timezone.strip()
        if not timezone:
            return False, "Timezone is required."
        errors: list[str] = []
        try:
            result = subprocess.run(
                ["timedatectl", "set-timezone", timezone],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception as exc:
            errors.append(f"timedatectl error: {exc}")
            result = None
        if result and result.returncode == 0:
            return True, f"Timezone updated to {timezone}."
        if result:
            error = (result.stderr or result.stdout or "").strip()
            if error:
                errors.append(error)

        zoneinfo_path = Path("/usr/share/zoneinfo") / timezone
        if not zoneinfo_path.exists():
            return False, " | ".join(errors) if errors else "Zoneinfo entry not found."
        try:
            localtime_path = Path("/etc/localtime")
            if localtime_path.exists() or localtime_path.is_symlink():
                localtime_path.unlink()
            localtime_path.symlink_to(zoneinfo_path)
            Path("/etc/timezone").write_text(f"{timezone}\n")
            return True, f"Timezone updated to {timezone} (fallback)."
        except Exception as exc:
            errors.append(f"fallback error: {exc}")
            return False, " | ".join(errors) if errors else "Unable to set timezone."
