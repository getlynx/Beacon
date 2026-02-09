 # LYNX TUI Installation
 
 ## Bootstrap install (placeholder URL)
 
 ```bash
 wget -qO- https://example.com/lynx-tui/bootstrap.sh | bash
 ```
 
 This downloads the installer into `/usr/local/lynx-tui/` and executes it as root.
 
 ## What the installer does
 
 - Installs OS packages: `python3`, `pip`, `htop`, `iptables`, `curl`.
 - Downloads the app bundle and installs it into a venv.
 - Installs `lynx-tui` launcher in `/usr/local/bin/`.
 - Creates systemd units and a sync-wait timer.
 - Starts the TUI automatically once the node sync completes.
 
 ## Configuration
 
 - Working directory: `/var/lib/lynx` (override with `LYNX_WORKING_DIR`)
 - RPC config: read from `lynx.conf` or env vars:
   - `LYNX_RPC_USER`
   - `LYNX_RPC_PASSWORD`
   - `LYNX_RPC_HOST`
   - `LYNX_RPC_PORT`
 
 ## Services
 
 - `lynx-sync-wait.timer`: checks sync status every 5 minutes
 - `lynx-tui.service`: runs the TUI once sync completes
 
 ## Manual start
 
 ```bash
 lynx-tui
 ```
