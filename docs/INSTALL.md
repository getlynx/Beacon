# Beacon Installation

## One-line install

```bash
bash <(curl -sL beacon.getlynx.io)
```

Run as root on a fresh VPS. The installer handles everything.

## What the installer does

- Detects OS (Debian/Ubuntu or RHEL/CentOS/Fedora).
- Installs OS packages: `python3`, `pip`, `venv`, `htop`, `iptables`, `curl`, `unzip`.
- Expands swap to 4 GB if current swap is under 3 GB (prevents out-of-memory during initial sync).
- Downloads and installs the Lynx daemon binary (`lynxd`, `lynx-cli`).
- Creates `lynx.service` systemd unit to run the daemon.
- Creates `lynx-sync-monitor` timer that restarts the daemon every 12 minutes during initial sync, then disables itself.
- Downloads the Beacon app bundle and installs it into a Python venv.
- Installs `/usr/local/bin/beacon` launcher.
- Adds a `beacon` alias and interactive-login autostart to `~/.bashrc`.

The TUI starts automatically on interactive SSH login (not on SFTP/SCP sessions).

## Configuration

- Working directory: `/var/lib/lynx` (override with `LYNX_WORKING_DIR`)
- RPC config: read from `lynx.conf` or env vars:
  - `LYNX_RPC_USER`
  - `LYNX_RPC_PASSWORD`
  - `LYNX_RPC_HOST`
  - `LYNX_RPC_PORT`

## Services

- `lynx.service`: runs the Lynx daemon.
- `lynx-sync-monitor.timer`: restarts the daemon every 12 minutes during initial block download, disables itself after sync completes.

## Auto-update

Beacon checks for new releases on GitHub once per hour. When a newer version is
available, the header shows a notice and the `u` key appears in the footer.
Press `u` to download and install the update in-place. After the update completes,
press `q` to quit and run `beacon` to restart with the new version.

The current Beacon version is shown in the Daemon Status card.

## Manual start

```bash
beacon
```
