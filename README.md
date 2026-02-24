# Beacon

Full-screen terminal UI for managing a Lynx blockchain node. Built with Textual.

## Quick start

```bash
bash <(curl -sL beacon.getlynx.io)
```

This installs the Lynx daemon, Beacon TUI, and all dependencies. The TUI starts
automatically on interactive SSH login. Run `beacon` manually at any time.

The node begins syncing immediately. The TUI is usable during sync and shows
progress. A sync-monitor service restarts the daemon periodically until sync completes.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Refresh all data |
| `s` | Toggle staking |
| `t` | Cycle theme |
| `c` | Create new address |
| `x` | Open send card |
| `w` | Open sweep card |
| `m` | Toggle map offset |
| `u` | Apply update (only visible when an update is available) |

## Auto-update

Beacon checks for new releases on GitHub once per hour. When a newer version is
found, the header displays an update notice and the `u` key appears in the footer.
Press `u` to download and install the update, then `q` to quit and run `beacon`
to restart with the new version.

## Development / Manual install

On systems with PEP 668 (externally-managed-environment), use the auto-venv launcher:

```bash
cd Beacon
./run
# or: python3 run
```

This creates `.venv` and installs dependencies on first run, then starts the TUI. No manual venv activation needed.

**Prerequisite (Debian/Ubuntu):** `apt install python3-venv`

**Manual venv** (optional):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python -m beacon
```
