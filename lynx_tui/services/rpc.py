import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests


class RpcClient:
    def __init__(self) -> None:
        self.working_dir = os.environ.get("LYNX_WORKING_DIR", "/var/lib/lynx")
        self.conf_path = os.environ.get("LYNX_CONF", f"{self.working_dir}/lynx.conf")
        self.rpc_user = os.environ.get("LYNX_RPC_USER")
        self.rpc_password = os.environ.get("LYNX_RPC_PASSWORD")
        self.rpc_host = os.environ.get("LYNX_RPC_HOST", "127.0.0.1")
        self.rpc_port = os.environ.get("LYNX_RPC_PORT")
        self._load_conf()

    def _load_conf(self) -> None:
        path = Path(self.conf_path)
        if not path.exists():
            return
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "rpcuser" and not self.rpc_user:
                self.rpc_user = value
            elif key == "rpcpassword" and not self.rpc_password:
                self.rpc_password = value
            elif key == "rpcport" and not self.rpc_port:
                self.rpc_port = value
            elif key == "rpcbind" and self.rpc_host == "127.0.0.1":
                self.rpc_host = value
            elif key == "rpchost" and self.rpc_host == "127.0.0.1":
                self.rpc_host = value

    def _rpc_url(self) -> str:
        port = self.rpc_port or "8332"
        return f"http://{self.rpc_host}:{port}"

    def _rpc_call(self, method: str, params: Optional[list] = None) -> Any:
        if not self.rpc_user or not self.rpc_password:
            raise RuntimeError("RPC credentials not configured")
        payload = {"jsonrpc": "1.0", "id": "lynx-tui", "method": method, "params": params or []}
        response = requests.post(
            self._rpc_url(),
            auth=(self.rpc_user, self.rpc_password),
            json=payload,
            timeout=3,
        )
        response.raise_for_status()
        data = response.json()
        if data.get("error"):
            raise RuntimeError(data["error"])
        return data.get("result")

    def _cli_call(self, method: str) -> Any:
        try:
            result = subprocess.run(
                ["lynx-cli", method],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        output = (result.stdout or "").strip()
        if not output:
            return None
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return output

    def _safe_call(self, method: str, params: Optional[list] = None) -> Any:
        try:
            return self._rpc_call(method, params)
        except Exception:
            if params:
                return None
            if method.startswith("get") or method in {"uptime"}:
                return self._cli_call(method)
            return None

    def _systemd_is_active(self, unit: str) -> str:
        try:
            result = subprocess.run(
                ["systemctl", "is-active", unit],
                check=False,
                capture_output=True,
                text=True,
            )
            status = (result.stdout or "").strip()
            return status if status else "unknown"
        except Exception:
            return "unknown"

    def fetch_node_version(self) -> Dict[str, Optional[str]]:
        try:
            result = subprocess.run(
                ["lynxd", "-version"],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            return {"name": None, "version_line": None, "version": None}
        if result.returncode != 0:
            return {"name": None, "version_line": None, "version": None}
        output = (result.stdout or "").strip().splitlines()
        if not output:
            return {"name": None, "version_line": None, "version": None}
        first_line = output[0].strip()
        if not first_line:
            return {"name": None, "version_line": None, "version": None}
        name = first_line.split()[0] if first_line.split() else None
        version = first_line.split()[-1] if first_line.split() else None
        return {"name": name, "version_line": first_line, "version": version}

    def fetch_block_count_cli(self) -> str:
        try:
            result = subprocess.run(
                ["lynx-cli", "getblockcount"],
                check=False,
                capture_output=True,
                text=True,
            )
        except Exception:
            return "loading"
        if result.returncode != 0:
            return "loading"
        output = (result.stdout or "").strip()
        return output if output.isdigit() else "loading"

    def _count_stakes(self, days: int) -> int:
        log_path = Path(self.working_dir) / "debug.log"
        if not log_path.exists():
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        count = 0
        for line in log_path.read_text(errors="ignore").splitlines():
            if "CheckStake(): New proof-of-stake block found" not in line:
                continue
            try:
                timestamp = line[:20]
                ts = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except Exception:
                continue
            if ts >= cutoff:
                count += 1
        return count

    def fetch_snapshot(self) -> Dict[str, Any]:
        blockchain = self._safe_call("getblockchaininfo") or {}
        best_block_hash = self._safe_call("getbestblockhash")
        chain_tips = self._safe_call("getchaintips") or []
        difficulty = self._safe_call("getdifficulty")
        mempool_info = self._safe_call("getmempoolinfo") or {}
        mining_info = self._safe_call("getmininginfo") or {}
        network_hashps = self._safe_call("getnetworkhashps")
        network_info = self._safe_call("getnetworkinfo") or {}
        net_totals = self._safe_call("getnettotals") or {}
        peers = self._safe_call("getpeerinfo") or []
        connection_count = self._safe_call("getconnectioncount")
        memory_info = self._safe_call("getmemoryinfo") or {}
        rpc_info = self._safe_call("getrpcinfo") or {}
        uptime = self._safe_call("uptime")
        wallet_info = self._safe_call("getwalletinfo") or {}
        balances = self._safe_call("getbalances") or {}
        unconfirmed_balance = self._safe_call("getunconfirmedbalance")

        balance = self._safe_call("getbalance") or 0
        listunspent = self._safe_call("listunspent") or []
        address_groups = self._safe_call("listaddressgroupings") or []

        immature_utxos = 0
        for utxo in listunspent:
            confirmations = utxo.get("confirmations", 0)
            if 0 < confirmations < 31:
                immature_utxos += 1

        stakes_24h = self._count_stakes(1)
        stakes_7d = self._count_stakes(7)
        yield_24h = round(stakes_24h * 100 / 288, 3)
        yield_7d = round(stakes_7d * 100 / 2016, 3)

        sync_state = "unknown"
        if isinstance(blockchain, dict):
            ibd = blockchain.get("initialblockdownload")
            sync_state = "synced" if ibd is False else "syncing"

        peer_count = len(peers) if isinstance(peers, list) else 0
        peer_list = ", ".join([p.get("addr", "?") for p in peers[:5]]) if peers else "-"

        daemon_status = "running" if blockchain else "unknown"
        staking_status = "unknown"
        if isinstance(blockchain, dict):
            staking_status = "unknown" if blockchain.get("initialblockdownload") else "staking"

        return {
            "blockchain_info": blockchain,
            "best_block_hash": best_block_hash,
            "chain_tips": chain_tips,
            "difficulty": difficulty,
            "mempool_info": mempool_info,
            "mining_info": mining_info,
            "network_hashps": network_hashps,
            "network_info": network_info,
            "net_totals": net_totals,
            "peer_info": peers,
            "connection_count": connection_count,
            "memory_info": memory_info,
            "rpc_info": rpc_info,
            "uptime": uptime,
            "wallet_info": wallet_info,
            "balances": balances,
            "unconfirmed_balance": unconfirmed_balance,
            "wallet_balance": balance,
            "immature_utxos": immature_utxos,
            "stakes_24h": stakes_24h,
            "stakes_7d": stakes_7d,
            "yield_24h": yield_24h,
            "yield_7d": yield_7d,
            "daemon_status": daemon_status,
            "staking_status": staking_status,
            "sync_state": sync_state,
            "block_height": blockchain.get("blocks", "-") if isinstance(blockchain, dict) else "-",
            "peer_count": peer_count,
            "peer_list": peer_list,
            "address_groups": len(address_groups) if isinstance(address_groups, list) else 0,
            "rpc_port": self.rpc_port or "8332",
            "rpc_security": "secure" if self.rpc_user and self.rpc_password else "unsecure",
            "working_dir": self.working_dir,
            "sync_monitor": self._systemd_is_active("lynx-sync-monitor.timer"),
        }
