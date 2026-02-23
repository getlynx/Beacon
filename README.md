# Beacon

Full-screen terminal UI for managing a LYNX blockchain node. Built with Textual.

## Quick start

```
wget -qO- https://github.com/getlynx/Beacon/releases/latest/download/bootstrap.sh | bash
```

This downloads and runs the installer, which sets up dependencies, installs the app,
and enables a sync-wait service that launches the TUI after the node finishes syncing.
It also adds a `beacon` alias and login autostart block to `~/.bashrc`.

Manual start: `beacon`

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
