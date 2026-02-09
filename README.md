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
