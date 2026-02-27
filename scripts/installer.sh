 #!/bin/bash
 
 set -euo pipefail
 
APP_TARBALL_URL="${APP_TARBALL_URL:-https://github.com/getlynx/Beacon/releases/latest/download/beacon.tar.gz}"
 INSTALL_ROOT="/usr/local/beacon"
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
     PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "3.11")
     apt-get install -y python3 python3-venv python3-pip "python${PYVER}-venv" "python${PYVER}-full" curl htop iptables unzip ufw
   elif [ "$OS_FAMILY" = "redhat" ]; then
    if command -v dnf >/dev/null 2>&1; then
      dnf install -y python3 python3-pip python3-virtualenv curl htop iptables unzip firewalld
     else
      yum install -y python3 python3-pip python3-virtualenv curl htop iptables unzip firewalld
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
  cat <<'EOF' > /usr/local/bin/beacon
#!/bin/bash
exec /usr/local/beacon/venv/bin/python -m beacon
EOF
   chmod +x /usr/local/bin/beacon
 }

update_login_bashrc() {
  local target_user="root"
  local target_home="/root"

  local bashrc="${target_home}/.bashrc"
  local marker_begin="# >>> beacon >>>"
  local marker_end="# <<< beacon <<<"
  local marker_begin_old="# >>> beacon-lynx-tui >>>"
  local marker_end_old="# <<< beacon-lynx-tui <<<"
  local block

  if [ ! -f "$bashrc" ]; then
    touch "$bashrc"
  fi

  block=$(cat <<'EOF'
# >>> beacon >>>
alias beacon="/usr/local/bin/beacon"
if [ "$(id -u)" -eq 0 ] && [[ $- == *i* ]] && [ -t 0 ] && [ -t 1 ] && command -v beacon >/dev/null 2>&1; then
  beacon
fi
# <<< beacon <<<
EOF
)

  local has_begin="false"
  local has_end="false"

  if grep -qF "$marker_begin" "$bashrc"; then
    has_begin="true"
  fi
  if grep -qF "$marker_end" "$bashrc"; then
    has_end="true"
  fi

  if [ "$has_begin" = "true" ] && [ "$has_end" = "true" ]; then
    awk -v begin="$marker_begin" -v end="$marker_end" -v new="$block" '
      $0 == begin { print new; skip = 1; next }
      $0 == end { skip = 0; next }
      !skip { print }
    ' "$bashrc" > "${bashrc}.tmp" && mv "${bashrc}.tmp" "$bashrc"
  elif grep -qF "$marker_begin_old" "$bashrc" && grep -qF "$marker_end_old" "$bashrc"; then
    awk -v begin="$marker_begin_old" -v end="$marker_end_old" -v new="$block" '
      $0 == begin { print new; skip = 1; next }
      $0 == end { skip = 0; next }
      !skip { print }
    ' "$bashrc" > "${bashrc}.tmp" && mv "${bashrc}.tmp" "$bashrc"
  else
    printf '\n%s\n' "$block" >> "$bashrc"
  fi

  chown "$target_user":"$target_user" "$bashrc" 2>/dev/null || true

  # Clean up beacon block from the invoking (non-root) user's .bashrc if present
  if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER:-}" != "root" ]; then
    local sudo_home
    sudo_home=$(getent passwd "${SUDO_USER}" | cut -d: -f6)
    local sudo_bashrc="${sudo_home}/.bashrc"
    if [ -f "$sudo_bashrc" ] && grep -qF "$marker_begin" "$sudo_bashrc"; then
      awk -v begin="$marker_begin" -v end="$marker_end" '
        $0 == begin { skip = 1; next }
        $0 == end { skip = 0; next }
        !skip { print }
      ' "$sudo_bashrc" > "${sudo_bashrc}.tmp" && mv "${sudo_bashrc}.tmp" "$sudo_bashrc"
      chown "${SUDO_USER}:${SUDO_USER}" "$sudo_bashrc" 2>/dev/null || true
      echo "Removed beacon auto-start from ${sudo_bashrc}"
    fi
    if [ -f "$sudo_bashrc" ] && grep -qF "$marker_begin_old" "$sudo_bashrc"; then
      awk -v begin="$marker_begin_old" -v end="$marker_end_old" '
        $0 == begin { skip = 1; next }
        $0 == end { skip = 0; next }
        !skip { print }
      ' "$sudo_bashrc" > "${sudo_bashrc}.tmp" && mv "${sudo_bashrc}.tmp" "$sudo_bashrc"
      chown "${SUDO_USER}:${SUDO_USER}" "$sudo_bashrc" 2>/dev/null || true
      echo "Removed legacy beacon auto-start from ${sudo_bashrc}"
    fi
  fi
}
 
ensure_swap() {
  local current_swap
  current_swap=$(free -m | awk '/^Swap:/ {print $2}')
  if [ "$current_swap" -ge 3072 ] 2>/dev/null; then
    echo "Swap is ${current_swap}MB (sufficient). Skipping."
    return 0
  fi
  echo "Swap is ${current_swap}MB. Expanding to 4GB..."

  if ! command -v mkswap >/dev/null 2>&1; then
    echo "mkswap not found. Skipping swap expansion."
    return 0
  fi

  if [ "$current_swap" -gt 0 ]; then
    local swap_dev
    swap_dev=$(tail -n1 /proc/swaps | awk '{print $1}')
    swapoff "$swap_dev" 2>/dev/null || true
    sed -i '/swap/d' /etc/fstab 2>/dev/null || true
  fi

  if command -v fallocate >/dev/null 2>&1; then
    fallocate -l 4G /swapfile 2>/dev/null
  fi
  if [ ! -f /swapfile ] || [ "$(stat -c%s /swapfile 2>/dev/null)" -lt 4000000000 ]; then
    dd if=/dev/zero of=/swapfile bs=1M count=4096 2>/dev/null || {
      echo "Could not create swapfile. Skipping."
      rm -f /swapfile
      return 0
    }
  fi

  chmod 600 /swapfile
  mkswap /swapfile >/dev/null 2>&1 || { echo "mkswap failed. Skipping."; rm -f /swapfile; return 0; }
  swapon /swapfile 2>/dev/null || { echo "swapon failed. Skipping."; rm -f /swapfile; return 0; }
  echo '/swapfile none swap sw 0 0' >> /etc/fstab 2>/dev/null || true
  echo "Swap expanded to 4GB."
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
    echo "ARM binary not in latest release. Checking release history..."
    all_releases=$(curl -fsSL --max-time 30 \
        "https://api.github.com/repos/${LYNX_REPO}/releases?per_page=10")
    if [ "$OS_FAMILY" = "debian" ]; then
      download_url=$(echo "$all_releases" | grep "browser_download_url" \
          | grep -iE "debian|ubuntu|ol" | grep -iE "\\.zip" \
          | grep -iE "arm" | head -n 1 | cut -d '"' -f 4)
    elif [ "$OS_FAMILY" = "redhat" ]; then
      download_url=$(echo "$all_releases" | grep "browser_download_url" \
          | grep -iE "rhel|centos|fedora|redhat|rocky|almalinux|ol" \
          | grep -iE "\\.zip" | grep -iE "arm" | head -n 1 | cut -d '"' -f 4)
    fi
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
TimeoutStartSec=600
TimeoutStopSec=60
WorkingDirectory=${WORKING_DIR}

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable lynx.service
  systemctl start --no-block lynx.service || true
}

install_sync_monitor() {
  mkdir -p "${INSTALL_ROOT}"
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
ExecStart=/usr/local/beacon/lynx-sync-monitor.sh
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

install_backup() {
  mkdir -p "${INSTALL_ROOT}"
  cat <<'BACKUP_EOF' > "${INSTALL_ROOT}/lynx-wallet-backup.sh"
#!/bin/bash
set -euo pipefail

WORKING_DIR="${LYNX_WORKING_DIR:-/var/lib/lynx}"
CHAIN_ID="${LYNX_CHAIN_ID:-lynx}"
BACKUP_DIR="/var/lib/${CHAIN_ID}-backup"
RPC_CLI="${LYNX_RPC_CLI:-/usr/local/bin/lynx-cli}"
LAST_HASH_FILE="${BACKUP_DIR}/.last-hash"
RETENTION_DAYS=90

mkdir -p "$BACKUP_DIR"

if [ ! -x "$RPC_CLI" ]; then
  echo "lynx-cli not found or not executable" >&2
  exit 1
fi

TIMESTAMP=$(date -u +"%Y-%m-%d-%H-%M-%S")
BACKUP_FILE="${BACKUP_DIR}/${TIMESTAMP}-${CHAIN_ID}.dat"

if ! "$RPC_CLI" -datadir="$WORKING_DIR" backupwallet "$BACKUP_FILE" 2>/dev/null; then
  echo "backupwallet failed" >&2
  exit 1
fi

NEW_HASH=$(sha256sum "$BACKUP_FILE" | cut -d' ' -f1)
if [ -f "$LAST_HASH_FILE" ]; then
  OLD_HASH=$(cat "$LAST_HASH_FILE")
  if [ "$NEW_HASH" = "$OLD_HASH" ]; then
    rm -f "$BACKUP_FILE"
    exit 0
  fi
fi
echo "$NEW_HASH" > "$LAST_HASH_FILE"

find "$BACKUP_DIR" -maxdepth 1 -name "*.dat" -mtime +$RETENTION_DAYS -delete 2>/dev/null || true

exit 0
BACKUP_EOF
  chmod +x "${INSTALL_ROOT}/lynx-wallet-backup.sh"

  CHAIN_ID="${LYNX_CHAIN_ID:-lynx}"
  BACKUP_DIR="/var/lib/${CHAIN_ID}-backup"
  mkdir -p "$BACKUP_DIR"
  chown lynx:lynx "$BACKUP_DIR" 2>/dev/null || true

  cat <<EOF > /etc/systemd/system/lynx-backup.service
[Unit]
Description=Lynx wallet backup (every 6 hours)
After=network.target lynx.service

[Service]
Type=oneshot
Environment=LYNX_WORKING_DIR=${WORKING_DIR}
Environment=LYNX_CHAIN_ID=lynx
ExecStart=${INSTALL_ROOT}/lynx-wallet-backup.sh
EOF

  cat <<'EOF' > /etc/systemd/system/lynx-backup.timer
[Unit]
Description=Run Lynx wallet backup every 6 hours

[Timer]
OnCalendar=*-*-* 00/6:00:00
Persistent=true
Unit=lynx-backup.service

[Install]
WantedBy=timers.target
EOF

  systemctl daemon-reload
  systemctl enable lynx-backup.timer
  systemctl start lynx-backup.timer
}

 main() {
   require_root
   detect_os
   install_packages
  ensure_swap
  ensure_working_dir
  install_lynx_binary
  install_lynx_service
  install_sync_monitor
  install_backup
   fetch_app
   install_app
   install_launcher
  update_login_bashrc
  echo "Beacon installed. Run 'beacon' or log in as root to start the TUI."
 }
 
 main "$@"
