 #!/bin/bash
 
 set -euo pipefail
 
APP_TARBALL_URL="${APP_TARBALL_URL:-https://example.com/lynx-tui/lynx-tui.tar.gz}"
 INSTALL_ROOT="/usr/local/lynx-tui"
 APP_DIR="${INSTALL_ROOT}/app"
 VENV_DIR="${INSTALL_ROOT}/venv"
WORKING_DIR="${LYNX_WORKING_DIR:-/var/lib/lynx}"
LYNX_REPO="getlynx/Lynx"
 
 require_root() {
   if [ "$EUID" -ne 0 ]; then
     echo "Please run as root."
     exit 1
   fi
 }
 
 detect_os() {
   if [ -f /etc/os-release ]; then
     . /etc/os-release
     case "$ID" in
       debian|ubuntu) OS_FAMILY="debian" ;;
       rhel|centos|fedora|rocky|almalinux|ol) OS_FAMILY="redhat" ;;
       *) OS_FAMILY="unknown" ;;
     esac
   else
     OS_FAMILY="unknown"
   fi
 }
 
 install_packages() {
   if [ "$OS_FAMILY" = "debian" ]; then
     apt-get update -y
    apt-get install -y python3 python3-venv python3-pip curl htop iptables unzip
   elif [ "$OS_FAMILY" = "redhat" ]; then
     if command -v dnf >/dev/null 2>&1; then
      dnf install -y python3 python3-pip python3-virtualenv curl htop iptables unzip
     else
      yum install -y python3 python3-pip python3-virtualenv curl htop iptables unzip
     fi
   else
     echo "Unsupported OS family. Install python3 and pip manually."
   fi
 }
 
 fetch_app() {
   mkdir -p "$APP_DIR"
   rm -rf "$APP_DIR"/*
   echo "Downloading app bundle..."
   if command -v curl >/dev/null 2>&1; then
    curl -fsSL --max-time 30 "$APP_TARBALL_URL" -o "${INSTALL_ROOT}/app.tar.gz"
   else
    wget -qO "${INSTALL_ROOT}/app.tar.gz" "$APP_TARBALL_URL"
   fi
   tar -xzf "${INSTALL_ROOT}/app.tar.gz" -C "$APP_DIR" --strip-components=1
 }
 
 install_app() {
   python3 -m venv "$VENV_DIR"
   "$VENV_DIR/bin/pip" install --upgrade pip
   "$VENV_DIR/bin/pip" install "$APP_DIR"
 }
 
 install_launcher() {
   cat <<'EOF' > /usr/local/bin/lynx-tui
#!/bin/bash
exec /usr/local/lynx-tui/venv/bin/python -m lynx_tui
EOF
   chmod +x /usr/local/bin/lynx-tui
 }
 
 install_sync_wait_script() {
   cat <<'EOF' > "${INSTALL_ROOT}/sync-wait.sh"
#!/bin/bash

set -euo pipefail

WORKING_DIR="${LYNX_WORKING_DIR:-/var/lib/lynx}"
RPC_CLI="/usr/local/bin/lynx-cli"

if [ ! -x "$RPC_CLI" ]; then
  exit 0
fi

info=$("$RPC_CLI" -datadir="$WORKING_DIR" getblockchaininfo 2>/dev/null || true)
if echo "$info" | grep -q '"initialblockdownload":[[:space:]]*false'; then
  systemctl enable lynx-tui.service >/dev/null 2>&1 || true
  systemctl start lynx-tui.service >/dev/null 2>&1 || true
  systemctl stop lynx-sync-wait.timer >/dev/null 2>&1 || true
  systemctl disable lynx-sync-wait.timer >/dev/null 2>&1 || true
fi
EOF
   chmod +x "${INSTALL_ROOT}/sync-wait.sh"
 }
 
ensure_working_dir() {
  mkdir -p "$WORKING_DIR"
  chmod 755 "$WORKING_DIR"
  if [ ! -e /root/.lynx ]; then
    ln -sf "$WORKING_DIR" /root/.lynx
  fi
}

install_lynx_binary() {
  if [ -x /usr/local/bin/lynxd ]; then
    return 0
  fi

  ARCH="$(uname -m)"
  echo "Fetching latest Lynx release info..."
  release_info=$(curl -fsSL --max-time 30 "https://api.github.com/repos/${LYNX_REPO}/releases/latest")

  if [ "$OS_FAMILY" = "debian" ]; then
    if [[ "$ARCH" == "aarch64" || "$ARCH" == arm* ]]; then
      download_url=$(echo "$release_info" | grep "browser_download_url" | grep -iE "debian|ubuntu|ol" | grep -iE "\\.zip" | grep -iE "arm" | head -n 1 | cut -d '"' -f 4)
    else
      download_url=$(echo "$release_info" | grep "browser_download_url" | grep -iE "debian|ubuntu|ol" | grep -iE "\\.zip" | grep -iE "amd" | head -n 1 | cut -d '"' -f 4)
    fi
  elif [ "$OS_FAMILY" = "redhat" ]; then
    if [[ "$ARCH" == "aarch64" || "$ARCH" == arm* ]]; then
      download_url=$(echo "$release_info" | grep "browser_download_url" | grep -iE "rhel|centos|fedora|redhat|rocky|almalinux|ol" | grep -iE "\\.zip" | grep -iE "arm" | head -n 1 | cut -d '"' -f 4)
    else
      download_url=$(echo "$release_info" | grep "browser_download_url" | grep -iE "rhel|centos|fedora|redhat|rocky|almalinux|ol" | grep -iE "\\.zip" | grep -iE "amd" | head -n 1 | cut -d '"' -f 4)
    fi
  else
    download_url=""
  fi

  if [ -z "$download_url" ]; then
    echo "No compatible Lynx binary found. Please install lynxd manually."
    return 1
  fi

  filename=$(basename "$download_url")
  echo "Downloading Lynx binary: $filename"
  curl -fsSL --max-time 60 "$download_url" -o "/root/$filename"
  unzip -o "/root/$filename" lynxd lynx-cli lynx-tx -d /usr/local/bin >/dev/null 2>&1
  rm -f "/root/$filename"
  chmod 755 /usr/local/bin/lynxd /usr/local/bin/lynx-cli /usr/local/bin/lynx-tx
}

install_lynx_service() {
  if [ -f /etc/systemd/system/lynx.service ]; then
    return 0
  fi

  cat <<EOF > /etc/systemd/system/lynx.service
[Unit]
Description=Lynx Cryptocurrency Daemon
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=forking
ExecStartPre=/bin/mkdir -p ${WORKING_DIR}
ExecStartPre=/bin/chown root:root ${WORKING_DIR}
ExecStart=/usr/local/bin/lynxd -datadir=${WORKING_DIR} -dbcache=2048
ExecStop=/usr/local/bin/lynx-cli -datadir=${WORKING_DIR} stop
Restart=on-failure
RestartSec=30
User=root
TimeoutStartSec=300
TimeoutStopSec=60
WorkingDirectory=${WORKING_DIR}

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable lynx.service
  systemctl start lynx.service || true
}

install_sync_monitor() {
  cat <<'EOF' > "${INSTALL_ROOT}/lynx-sync-monitor.sh"
#!/bin/bash

set -euo pipefail

WORKING_DIR="${LYNX_WORKING_DIR:-/var/lib/lynx}"
RPC_CLI="/usr/local/bin/lynx-cli"

if [ ! -x "$RPC_CLI" ]; then
  exit 0
fi

info=$("$RPC_CLI" -datadir="$WORKING_DIR" getblockchaininfo 2>/dev/null || true)
if echo "$info" | grep -q '"initialblockdownload":[[:space:]]*false'; then
  systemctl stop lynx-sync-monitor.timer >/dev/null 2>&1 || true
  systemctl disable lynx-sync-monitor.timer >/dev/null 2>&1 || true
else
  systemctl restart lynx.service >/dev/null 2>&1 || true
fi
EOF
  chmod +x "${INSTALL_ROOT}/lynx-sync-monitor.sh"

  cat <<'EOF' > /etc/systemd/system/lynx-sync-monitor.service
[Unit]
Description=Restart Lynx during sync
After=network.target lynx.service

[Service]
Type=oneshot
ExecStart=/usr/local/lynx-tui/lynx-sync-monitor.sh
EOF

  cat <<'EOF' > /etc/systemd/system/lynx-sync-monitor.timer
[Unit]
Description=Restart Lynx every 12 minutes during sync

[Timer]
OnBootSec=2min
OnUnitActiveSec=12min
Unit=lynx-sync-monitor.service

[Install]
WantedBy=timers.target
EOF

  systemctl daemon-reload
  systemctl enable lynx-sync-monitor.timer
  systemctl start lynx-sync-monitor.timer
}

 install_systemd_units() {
   cat <<'EOF' > /etc/systemd/system/lynx-tui.service
[Unit]
Description=LYNX TUI
After=network.target lynx.service
Wants=network.target

[Service]
Type=simple
ExecStart=/usr/local/bin/lynx-tui
Restart=on-failure
User=root
WorkingDirectory=/root
Environment=LYNX_WORKING_DIR=/var/lib/lynx

[Install]
WantedBy=multi-user.target
EOF

   cat <<'EOF' > /etc/systemd/system/lynx-sync-wait.service
[Unit]
Description=Wait for LYNX sync completion
After=network.target lynx.service

[Service]
Type=oneshot
ExecStart=/usr/local/lynx-tui/sync-wait.sh
EOF

   cat <<'EOF' > /etc/systemd/system/lynx-sync-wait.timer
[Unit]
Description=Check LYNX sync status

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Unit=lynx-sync-wait.service

[Install]
WantedBy=timers.target
EOF

   systemctl daemon-reload
   systemctl enable lynx-sync-wait.timer
   systemctl start lynx-sync-wait.timer
 }
 
 main() {
   require_root
   detect_os
   install_packages
  ensure_working_dir
  install_lynx_binary
  install_lynx_service
  install_sync_monitor
   fetch_app
   install_app
   install_launcher
   install_sync_wait_script
   install_systemd_units
   echo "LYNX TUI installed. It will start automatically after sync completes."
 }
 
 main "$@"
