import os
import re
from datetime import datetime, timezone
from pathlib import Path


class LogTailer:
    def __init__(self) -> None:
        self.working_dir = os.environ.get("LYNX_WORKING_DIR", "/var/lib/lynx")
        self.log_path = Path(self.working_dir) / "debug.log"
        # Fallback to ~/.lynx if primary location doesn't exist
        if not self.log_path.exists():
            fallback_path = Path.home() / ".lynx" / "debug.log"
            if fallback_path.exists():
                self.log_path = fallback_path
        self.max_lines = 200

    def tail_lines(self) -> list[str]:
        if not self.log_path.exists():
            return ["debug.log not found"]
        try:
            lines = self.log_path.read_text(errors="ignore").splitlines()
        except Exception:
            return ["Unable to read debug.log"]
        return lines[-self.max_lines :]

    def get_update_tip_entries(
        self, limit: int = 15
    ) -> tuple[
        list[tuple[int, str, str, str, str]],
        datetime | None,
        str,
    ]:
        """Return (entries, latest_time, tz_name). Time display excludes timezone (shown in card subtitle)."""
        if not self.log_path.exists():
            return ([(0, "-", "debug.log not found", "-", "-")], None, "")
        try:
            lines = self.log_path.read_text(errors="ignore").splitlines()
        except Exception:
            return ([(0, "-", "Unable to read debug.log", "-", "-")], None, "")

        entries: list[tuple[int, str, str, datetime | None, int | None]] = []
        seen: set[int] = set()
        height_re = re.compile(r"\bheight=(\d+)\b")
        hash_re = re.compile(r"(?:best|hash)=([0-9a-fA-F]{8,64})")
        fallback_hash_re = re.compile(r"\b([0-9a-fA-F]{8,64})\b")
        tx_re = re.compile(r"\btx=(\d+)\b")

        for line in reversed(lines):
            if "UpdateTip" not in line:
                continue
            height_match = height_re.search(line)
            height = int(height_match.group(1)) if height_match else -1
            hash_match = hash_re.search(line) or fallback_hash_re.search(line)
            hash_value = hash_match.group(1) if hash_match else "-"
            hash_short = hash_value[:4] if hash_value != "-" else "-"

            timestamp = line.split(" ", 1)[0]
            time_display = timestamp.replace("T", " ")
            parsed_time: datetime | None = None
            try:
                parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                local_time = parsed.astimezone()
                time_display = local_time.strftime("%Y-%m-%d %I:%M:%S %p")
                parsed_time = local_time
            except Exception:
                if len(time_display) > 19:
                    time_display = time_display[:19]

            tx_match = tx_re.search(line)
            tx_count = int(tx_match.group(1)) if tx_match else None
            if height in seen:
                continue
            seen.add(height)
            entries.append((height, hash_short, time_display, parsed_time, tx_count))
            if len(entries) >= 200:
                break

        if not entries:
            return ([(0, "-", "No UpdateTip entries.", "-", "-")], None, "")

        entries.sort(key=lambda item: item[0], reverse=True)
        latest_time = entries[0][3] if entries else None
        tz_name = ""
        if latest_time and latest_time.tzinfo:
            tz_name = latest_time.strftime("%Z") or str(latest_time.tzinfo)
        result_lines: list[tuple[int, str, str, str, str]] = []
        max_items = min(limit, len(entries))
        for index in range(max_items):
            height, hash_short, time_display, parsed_time, tx_count = entries[index]
            delta_display = "-"
            empty_marker = ""
            if index + 1 < len(entries):
                next_time = entries[index + 1][3]
                next_tx = entries[index + 1][4]
                if parsed_time and next_time:
                    delta_seconds = int((parsed_time - next_time).total_seconds())
                    if delta_seconds < 0:
                        delta_seconds = abs(delta_seconds)
                    minutes, seconds = divmod(delta_seconds, 60)
                    if minutes:
                        delta_display = f"{minutes}m {seconds}s"
                    else:
                        delta_display = f"{seconds}s"
                if tx_count is not None and next_tx is not None:
                    if next_tx == tx_count - 2:
                        empty_marker = "empty"
                    else:
                        diff = abs(tx_count - next_tx) - 2
                        if diff < 0:
                            diff = 0
                        empty_marker = f"{diff} tx"
            result_lines.append((height, hash_short, time_display, delta_display, empty_marker))
        return (result_lines, latest_time, tz_name)

    def get_latest_block_statistics(self) -> str:
        """Get the most recent Block Statistics line from debug.log."""
        if not self.log_path.exists():
            return "Block Statistics: debug.log not found"
        try:
            lines = self.log_path.read_text(errors="ignore").splitlines()
        except Exception:
            return "Block Statistics: Unable to read debug.log"
        
        # Search from the end for the latest Block Statistics line
        for line in reversed(lines):
            if "Block Statistics" in line:
                # Extract just the statistics part after the timestamp
                parts = line.split("Block Statistics - ", 1)
                if len(parts) == 2:
                    return f"Block Statistics - {parts[1].strip().replace(chr(13), '').replace(chr(10), '')}"
                return line.strip().replace("\r", "").replace("\n", "")
        
        return "Block Statistics: Not yet available"
