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
        self.datadir: str | None = None  # from lynx.conf datadir=
        self.rpc_user = os.environ.get("LYNX_RPC_USER")
        self.rpc_password = os.environ.get("LYNX_RPC_PASSWORD")
        self.rpc_host = os.environ.get("LYNX_RPC_HOST", "127.0.0.1")
        self.rpc_port = os.environ.get("LYNX_RPC_PORT")
        self._load_conf()

    def _load_conf(self) -> None:
        path = Path(self.conf_path)
        if not path.exists():
            return
        conf_dir = str(path.parent)
        lines = path.read_text().splitlines()
        testnet = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "testnet":
                try:
                    testnet = int(value)
                except (TypeError, ValueError):
                    pass
                break
        prefix = "test." if testnet else "main."
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "datadir":
                self.datadir = value
                if not os.path.isabs(value):
                    self.datadir = os.path.normpath(os.path.join(conf_dir, value))
            elif key == "rpcuser" and not self.rpc_user:
                self.rpc_user = value
            elif key == "rpcpassword" and not self.rpc_password:
                self.rpc_password = value
            elif key == "rpcport" and not self.rpc_port:
                self.rpc_port = value
            elif key == "rpcbind" and self.rpc_host == "127.0.0.1":
                self.rpc_host = value
            elif key == "rpchost" and self.rpc_host == "127.0.0.1":
                self.rpc_host = value
            elif key == f"{prefix}rpcuser" and not self.rpc_user:
                self.rpc_user = value
            elif key == f"{prefix}rpcpassword" and not self.rpc_password:
                self.rpc_password = value
            elif key == f"{prefix}rpcport" and not self.rpc_port:
                self.rpc_port = value

    def get_datadir(self) -> str:
        """Return the effective LYNX data directory (datadir from conf, else working_dir, else fallbacks)."""
        if self.datadir:
            return self.datadir
        if self.working_dir:
            path = Path(self.working_dir)
            if path.exists():
                return str(path.resolve())
        # Fallbacks: ~/.lynx is common on Linux
        for candidate in [
            os.path.expanduser("~/.lynx"),
            "/root/.lynx",
            "/var/lib/lynx",
        ]:
            if os.path.isdir(candidate):
                return candidate
        return self.working_dir

    def get_staking_enabled_from_config(self) -> bool | None:
        """Check if staking is enabled based on disablestaking config.
        
        Returns:
            True if staking is enabled (disablestaking=0 or not set)
            False if staking is disabled (disablestaking=1)
            None if config file doesn't exist
        """
        path = Path(self.conf_path)
        if not path.exists():
            return None
        
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            
            if key == "disablestaking":
                # disablestaking=1 means staking is OFF
                # disablestaking=0 means staking is ON
                if value == "1":
                    return False
                elif value == "0":
                    return True
        
        # If disablestaking is not in config, assume staking is enabled
        return True

    def _rpc_url(self) -> str:
        port = self.rpc_port or "9332"
        return f"http://{self.rpc_host}:{port}"

    def _rpc_call(self, method: str, params: Optional[list] = None) -> Any:
        """HTTP JSON-RPC call. Raises on failure."""
        if not self.rpc_user or not self.rpc_password:
            raise RuntimeError("RPC credentials not configured")
        payload = {"jsonrpc": "1.0", "id": "beacon", "method": method, "params": params or []}
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
    
    def _cli_call_with_params(self, method: str, params: list) -> Any:
        """Call lynx-cli with parameters."""
        try:
            # Convert params to strings, handling booleans properly
            str_params = []
            for p in params:
                if isinstance(p, bool):
                    str_params.append("true" if p else "false")
                else:
                    str_params.append(str(p))
            
            cmd = ["lynx-cli", method] + str_params
            result = subprocess.run(
                cmd,
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

    def getnewaddress(self) -> Optional[str]:
        """Generate a new receiving address. Returns the address string or None on failure."""
        result = self._safe_call("getnewaddress")
        return str(result) if result is not None else None

    def sendtoaddress(self, address: str, amount: float) -> tuple[bool, str]:
        """Send LYNX to an address. Returns (success, txid_or_error_message)."""
        addr = address.strip()
        if not addr:
            return False, "Address is required"
        try:
            amt = float(amount)
        except (TypeError, ValueError):
            return False, "Invalid amount"
        if amt <= 0:
            return False, "Amount must be positive"
        err_msg = "Send failed"
        try:
            result = self._rpc_call("sendtoaddress", [addr, amt])
            return True, str(result) if result is not None else "Sent"
        except Exception:
            pass
        result = self._cli_call_with_params("sendtoaddress", [addr, amt])
        if result is not None:
            txid = result.get("txid", result) if isinstance(result, dict) else result
            return True, str(txid)
        return False, err_msg

    def sweep_to_address(self, address: str) -> tuple[bool, str]:
        """Sweep full balance to an address. Uses sendtoaddress(addr, getbalance(), "", "", true).
        Returns (success, txid_or_error_message)."""
        addr = address.strip()
        if not addr:
            return False, "Address is required"
        err_msg = "Sweep failed"
        balance = self._safe_call("getbalance")
        bal = float(balance) if balance is not None else 0.0
        if bal <= 0:
            return False, "No balance to sweep"
        try:
            result = self._rpc_call("sendtoaddress", [addr, bal, "", "", True])
            return True, str(result) if result is not None else "Swept"
        except Exception:
            pass
        result = self._cli_call_with_params("sendtoaddress", [addr, bal, "", "", True])
        if result is not None:
            txid = result.get("txid", result) if isinstance(result, dict) else result
            return True, str(txid)
        return False, err_msg

    def _safe_call(self, method: str, params: Optional[list] = None) -> Any:
        """HTTP first, CLI fallback."""
        try:
            return self._rpc_call(method, params)
        except Exception:
            pass
        if params:
            result = self._cli_call_with_params(method, params)
            if result is not None:
                return result
        if method.startswith("get") or method.startswith("list") or method in {"uptime"}:
            result = self._cli_call(method)
            if result is not None:
                return result
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

    def getblockhash(self, height: int) -> str | None:
        """Return block hash at given height."""
        return self._safe_call("getblockhash", [height])

    def getblock(self, block_hash: str, verbosity: int = 1) -> Dict[str, Any] | None:
        """Fetch block details. Verbosity 1 returns hash, height, tx array."""
        try:
            result = self._rpc_call("getblock", [block_hash, verbosity])
            if result is not None and isinstance(result, dict):
                return result
        except Exception:
            pass
        result = self._cli_call_with_params("getblock", [block_hash, str(verbosity)])
        if result is not None and isinstance(result, dict):
            return result
        return None

    def get_backup_dir(self) -> str:
        """Return the backup directory: /var/lib/{chain-name}-backup/."""
        chain_id = self._get_chain_id()
        return f"/var/lib/{chain_id}-backup"

    def _get_chain_id(self) -> str:
        """Return chain identifier from config filename (lynx.conf -> lynx) or env."""
        chain = os.environ.get("LYNX_CHAIN_ID")
        if chain:
            return chain
        conf = Path(self.conf_path)
        if conf.exists():
            name = conf.stem.lower()
            if name and name != "conf":
                return name
        return "lynx"

    def backupwallet(self, destination: str) -> tuple[bool, str]:
        """Run backupwallet RPC. Returns (success, message)."""
        try:
            self._rpc_call("backupwallet", [destination])
            return True, "OK"
        except Exception:
            pass
        result = self._cli_call_with_params("backupwallet", [destination])
        if result is not None:
            return True, "OK"
        if self._cli_run_ok("backupwallet", [destination]):
            return True, "OK"
        return False, "Backup failed"

    def _cli_run_ok(self, method: str, params: list) -> bool:
        """Run lynx-cli; returns True if exit code 0 (success even with empty output)."""
        rpc_cli = os.environ.get("LYNX_RPC_CLI", "lynx-cli")
        try:
            str_params = [str(p) for p in params]
            r = subprocess.run([rpc_cli, method] + str_params, check=False, capture_output=True, text=True)
            return r.returncode == 0
        except Exception:
            return False

    def list_backups(self) -> list[dict]:
        """Scan backup dir for .dat files. Returns list of {path, mtime, date_str, filename} sorted by mtime desc."""
        backup_dir = self.get_backup_dir()
        path = Path(backup_dir)
        if not path.is_dir():
            return []
        result: list[dict] = []
        for f in path.glob("*.dat"):
            try:
                stat = f.stat()
                mtime = stat.st_mtime
                date_str = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                result.append({"path": str(f), "mtime": mtime, "date_str": date_str, "filename": f.name})
            except OSError:
                continue
        result.sort(key=lambda x: x["mtime"], reverse=True)
        return result

    def restore_wallet(self, backup_path: str) -> tuple[bool, str]:
        """Restore wallet from backup. Uses unloadwallet, copy, loadwallet. Returns (success, message)."""
        import shutil

        datadir = self.get_datadir()
        wallet_dat = os.path.join(datadir, "wallet.dat")
        backup_path = os.path.abspath(backup_path)
        if not os.path.isfile(backup_path):
            return False, "Backup file not found"
        wallets = self._safe_call("listwallets") or []
        wallet_name = wallets[0] if wallets else ""
        unload_params = [wallet_name] if wallet_name else []
        try:
            self._rpc_call("unloadwallet", unload_params)
        except Exception:
            if not self._cli_run_ok("unloadwallet", unload_params):
                return False, "Unload failed"
        try:
            shutil.copy2(backup_path, wallet_dat)
        except Exception as e:
            try:
                self._rpc_call("loadwallet", [wallet_dat])
            except Exception:
                self._cli_run_ok("loadwallet", [wallet_dat])
            return False, f"Copy failed: {e}"
        try:
            self._rpc_call("loadwallet", [wallet_dat])
            return True, "Restored"
        except Exception:
            if not self._cli_run_ok("loadwallet", [wallet_dat]):
                return False, "Load failed"
            return True, "Restored"

    def get_size_on_disk(self) -> int | None:
        """Return blockchain size on disk in bytes (from getblockchaininfo.size_on_disk)."""
        try:
            info = self._safe_call("getblockchaininfo")
            if isinstance(info, dict):
                size = info.get("size_on_disk")
                if isinstance(size, (int, float)) and size >= 0:
                    return int(size)
        except Exception:
            pass
        return None

    def encrypt_wallet(self, passphrase: str) -> tuple[bool, str]:
        """Encrypt wallet with passphrase (first-time only). Returns (success, message)."""
        try:
            self._rpc_call("encryptwallet", [passphrase])
            return True, "OK"
        except Exception:
            pass
        result = self._cli_call_with_params("encryptwallet", [passphrase])
        if result is not None:
            return True, "OK"
        if self._cli_run_ok("encryptwallet", [passphrase]):
            return True, "OK"
        return False, "Encryption failed"

    def wallet_passphrase(self, passphrase: str, timeout_seconds: int) -> tuple[bool, str]:
        """Unlock wallet for staking. Timeout in seconds. Returns (success, message)."""
        try:
            self._rpc_call("walletpassphrase", [passphrase, timeout_seconds])
            return True, "OK"
        except Exception:
            pass
        result = self._cli_call_with_params("walletpassphrase", [passphrase, timeout_seconds])
        if result is not None:
            return True, "OK"
        if self._cli_run_ok("walletpassphrase", [passphrase, timeout_seconds]):
            return True, "OK"
        return False, "Unlock failed"

    def wallet_lock(self) -> tuple[bool, str]:
        """Lock the wallet. HTTP first, CLI fallback."""
        try:
            self._rpc_call("walletlock", [])
            return True, "OK"
        except Exception:
            pass
        result = self._cli_call("walletlock")
        if result is not None:
            return True, "OK"
        if self._cli_run_ok("walletlock", []):
            return True, "OK"
        return False, "Lock failed"

    def set_staking(self, enabled: bool) -> Any:
        """Enable or disable staking. HTTP first, CLI fallback."""
        command = "true" if enabled else "false"
        try:
            return self._rpc_call("setstaking", [command])
        except Exception:
            pass
        result = self._cli_call_with_params("setstaking", [command])
        if result is not None:
            return result
        if self._cli_run_ok("setstaking", [command]):
            return command
        return None

    def get_wallet_encryption_status(self) -> dict:
        """Return encryption status from getwalletinfo. encrypted=True if passphrase set; unlocked_until=0 when locked."""
        info = self._safe_call("getwalletinfo") or {}
        if not isinstance(info, dict):
            return {}
        unlocked_until = info.get("unlocked_until")
        encrypted = unlocked_until is not None
        if not encrypted and isinstance(info.get("encryption_status"), str):
            enc = str(info.get("encryption_status", "")).lower()
            encrypted = "locked" in enc or "encrypted" in enc
        return {
            "encrypted": encrypted,
            "unlocked_until": unlocked_until,
            "locked": encrypted and (unlocked_until is None or unlocked_until == 0),
        }

    def get_daemon_status(self) -> str:
        """Return 'running' if daemon responds, else 'unknown'."""
        blockchain = self._safe_call("getblockchaininfo") or {}
        return "running" if blockchain else "unknown"

    def fetch_capacity(self) -> Dict[str, Any] | None:
        """Fetch storage capacity via lynx-cli capacity (hidden RPC). Returns JSON with values in KB."""
        datadir = self.get_datadir()
        for args in [
            ["lynx-cli", "capacity"],
            ["lynx-cli", "-datadir=" + datadir, "capacity"],
        ]:
            try:
                result = subprocess.run(
                    args,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except Exception:
                continue
            if result.returncode != 0:
                continue
            output = (result.stdout or "").strip()
            if not output:
                continue
            try:
                data = json.loads(output)
                if data is not None:
                    return data
            except json.JSONDecodeError:
                continue
        return None

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
        log_path = Path(self.get_datadir()) / "debug.log"
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
        # Get all addresses including empty ones
        all_addresses = self._safe_call("listreceivedbyaddress", [0, True]) or []

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
            "address_groups": address_groups,
            "all_addresses": all_addresses,
            "rpc_port": self.rpc_port or "8332",
            "rpc_security": "secure" if self.rpc_user and self.rpc_password else "unsecure",
            "working_dir": self.working_dir,
            "sync_monitor": self._systemd_is_active("lynx-sync-monitor.timer"),
        }
