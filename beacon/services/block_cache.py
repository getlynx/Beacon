"""Persistent on-disk cache for block tx/shard counts.

Stores a JSON file mapping block height -> [tx_count, shard_count].
Since this data is immutable once a block is confirmed, it never needs
invalidation.
"""

import json
import os

_DEFAULT_PATH = "/var/lib/lynx/.beacon-block-cache.json"


class BlockCache:
    def __init__(self, path: str | None = None) -> None:
        self._path = path or os.environ.get("BEACON_BLOCK_CACHE", _DEFAULT_PATH)
        self._data: dict[int, tuple[int, int]] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "r") as f:
                raw = json.load(f)
            # JSON keys are strings — convert to int
            self._data = {int(k): (v[0], v[1]) for k, v in raw.items()}
        except (FileNotFoundError, json.JSONDecodeError, ValueError, TypeError):
            self._data = {}

    def get(self, height: int) -> tuple[int, int] | None:
        return self._data.get(height)

    def put(self, height: int, tx_count: int, shard_count: int) -> None:
        if self._data.get(height) == (tx_count, shard_count):
            return
        self._data[height] = (tx_count, shard_count)
        self._dirty = True

    def flush(self) -> None:
        """Write to disk if there are pending changes."""
        if not self._dirty:
            return
        try:
            tmp = self._path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self._data, f, separators=(",", ":"))
            os.replace(tmp, self._path)
            self._dirty = False
        except OSError:
            pass

    def __contains__(self, height: int) -> bool:
        return height in self._data

    def __len__(self) -> int:
        return len(self._data)
