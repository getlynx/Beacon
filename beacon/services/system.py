import os
import subprocess
from pathlib import Path
from typing import Tuple, Dict, Any


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

    def get_system_stats(self) -> Dict[str, Any]:
        """Get system utilization statistics."""
        stats = {
            "uptime": "-",
            "cpu_percent": 0.0,
            "cpu_cores": 0,
            "load_avg": [0.0, 0.0, 0.0],
            "memory_percent": 0.0,
            "memory_used_gb": 0.0,
            "memory_total_gb": 0.0,
            "swap_used_gb": 0.0,
            "swap_total_gb": 0.0,
            "network_down_kb": 0.0,
            "network_up_kb": 0.0,
        }
        
        try:
            import psutil
            
            # Uptime
            boot_time = psutil.boot_time()
            uptime_seconds = psutil.time.time() - boot_time
            days, remainder = divmod(int(uptime_seconds), 86400)
            hours, remainder = divmod(remainder, 3600)
            minutes, seconds = divmod(remainder, 60)
            if days > 0:
                stats["uptime"] = f"{days} days, {hours:02d}:{minutes:02d}:{seconds:02d}"
            else:
                stats["uptime"] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            
            # CPU
            stats["cpu_percent"] = psutil.cpu_percent(interval=0.1)
            stats["cpu_cores"] = psutil.cpu_count()
            
            # Load average
            if hasattr(os, 'getloadavg'):
                stats["load_avg"] = list(os.getloadavg())
            
            # Memory
            mem = psutil.virtual_memory()
            stats["memory_percent"] = mem.percent
            stats["memory_used_gb"] = mem.used / (1024 ** 3)
            stats["memory_total_gb"] = mem.total / (1024 ** 3)
            
            # Swap
            swap = psutil.swap_memory()
            stats["swap_used_gb"] = swap.used / (1024 ** 3)
            stats["swap_total_gb"] = swap.total / (1024 ** 3)
            
            # Network - get current totals (we'll calculate rate in the app)
            net_io = psutil.net_io_counters()
            stats["network_down_kb"] = net_io.bytes_recv / 1024
            stats["network_up_kb"] = net_io.bytes_sent / 1024
            
        except ImportError:
            # psutil not available, use fallback methods
            try:
                # Uptime from /proc/uptime
                with open('/proc/uptime', 'r') as f:
                    uptime_seconds = float(f.read().split()[0])
                    days, remainder = divmod(int(uptime_seconds), 86400)
                    hours, remainder = divmod(remainder, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    if days > 0:
                        stats["uptime"] = f"{days} days, {hours:02d}:{minutes:02d}:{seconds:02d}"
                    else:
                        stats["uptime"] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
            except:
                pass
            
            try:
                # Load average
                if hasattr(os, 'getloadavg'):
                    stats["load_avg"] = list(os.getloadavg())
            except:
                pass
            
            try:
                # Memory from /proc/meminfo
                with open('/proc/meminfo', 'r') as f:
                    meminfo = {}
                    for line in f:
                        parts = line.split(':')
                        if len(parts) == 2:
                            key = parts[0].strip()
                            value = parts[1].strip().split()[0]
                            meminfo[key] = int(value)
                    
                    total = meminfo.get('MemTotal', 0)
                    available = meminfo.get('MemAvailable', 0)
                    if total > 0:
                        used = total - available
                        stats["memory_percent"] = (used / total) * 100
                        stats["memory_used_gb"] = used / (1024 ** 2)
                        stats["memory_total_gb"] = total / (1024 ** 2)
                    
                    swap_total = meminfo.get('SwapTotal', 0)
                    swap_free = meminfo.get('SwapFree', 0)
                    if swap_total > 0:
                        swap_used = swap_total - swap_free
                        stats["swap_used_gb"] = swap_used / (1024 ** 2)
                        stats["swap_total_gb"] = swap_total / (1024 ** 2)
            except:
                pass
            
            try:
                # CPU cores
                stats["cpu_cores"] = os.cpu_count() or 0
            except:
                pass
        
        except Exception:
            pass
        
        return stats

    def get_disk_and_lynx_stats(
        self, lynx_working_dir: str | None = None
    ) -> Dict[str, Any]:
        """Get disk usage for root '/' (used as 'total disk' reference).
        Returns dict with disk_total_bytes, disk_used_bytes, disk_percent.
        """
        # Use root "/" as reference for "total disk" - consistent across setups.
        # (size_on_disk from RPC is blockchain size; we compare to main system disk)
        disk_path = "/"

        stats = {
            "disk_total_bytes": 0,
            "disk_used_bytes": 0,
            "disk_percent": 0.0,
        }

        try:
            import psutil
            du = psutil.disk_usage(disk_path)
            stats["disk_total_bytes"] = du.total
            stats["disk_used_bytes"] = du.used
            stats["disk_percent"] = du.percent
        except Exception:
            pass

        # Fallback: df -B1 for byte-sized output when psutil fails or returns 0
        if stats["disk_total_bytes"] <= 0:
            try:
                result = subprocess.run(
                    ["df", "-B1", disk_path],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout:
                    lines = result.stdout.strip().splitlines()
                    if len(lines) >= 2:
                        parts = lines[1].split()
                        if len(parts) >= 2:
                            total = int(parts[1])  # 1K-blocks col, -B1 makes it bytes
                            used = int(parts[2]) if len(parts) >= 3 else 0
                            stats["disk_total_bytes"] = total
                            stats["disk_used_bytes"] = used
                            stats["disk_percent"] = (
                                100.0 * used / total if total > 0 else 0.0
                            )
            except (subprocess.SubprocessError, ValueError, IndexError):
                pass

        return stats
