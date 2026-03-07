#!/bin/bash
# ElectrumX install for Beacon: uses existing Lynx node at LYNX_WORKING_DIR.
# Requires root. Set ELECTRUMX_DOMAIN for SSL (e.g. electrum.example.com); omit for RPC-only.
set -euo pipefail

LYNX_WORKING_DIR="${LYNX_WORKING_DIR:-/var/lib/lynx}"
LYNX_CONF="${LYNX_WORKING_DIR}/lynx.conf"
ELECTRUMX_CONF="/etc/electrumx.conf"
ELECTRUMX_SSL_PORT="50002"
ELECTRUMX_WSS_PORT="50004"

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root."
  exit 1
fi

if [ ! -f "$LYNX_CONF" ]; then
  echo "Lynx config not found at $LYNX_CONF. Sync the node first."
  exit 1
fi

# RPC from lynx.conf (Beacon default path)
rpcuser="$(sed -ne 's|[ \t]*rpcuser=[ \t]*||p' "$LYNX_CONF" | tr -d '\r')"
rpcpassword="$(sed -ne 's|[ \t]*rpcpassword=[ \t]*||p' "$LYNX_CONF" | tr -d '\r')"
rpcport="$(sed -ne 's|[ \t]*rpcport=[ \t]*||p' "$LYNX_CONF" | tr -d '\r')"
rpcport="${rpcport:-9332}"

if [ -z "$rpcuser" ] || [ -z "$rpcpassword" ]; then
  echo "Could not read rpcuser/rpcpassword from $LYNX_CONF"
  exit 1
fi

# Install ElectrumX if not present (bootstrap)
if ! command -v electrumx_server &>/dev/null; then
  echo "Installing ElectrumX..."
  apt-get update -y
  set +e
  apt-get install -y git python3-pip gcc g++ build-essential \
    libsnappy-dev zlib1g-dev libbz2-dev liblz4-dev libzstd-dev libleveldb-dev
  apt_ret=$?
  set -e
  if [ $apt_ret -ne 0 ]; then
    echo "apt-get install had errors (exit $apt_ret). Trying optional packages separately..."
    apt-get install -y libleveldb-dev 2>/dev/null || true
  fi
  # If ~/.electrumx-installer already exists (e.g. from a previous run), use its install.sh
  INSTALLER_HOME="${SUDO_HOME:-$HOME}"
  [ -z "$INSTALLER_HOME" ] && INSTALLER_HOME="/root"
  if [ -x "$INSTALLER_HOME/.electrumx-installer/install.sh" ]; then
    echo "Found existing $INSTALLER_HOME/.electrumx-installer; running its install.sh ..."
    set +e
    "$INSTALLER_HOME/.electrumx-installer/install.sh"
    install_ret=$?
    set -e
    if [ $install_ret -eq 0 ] && command -v electrumx_server &>/dev/null; then
      echo "ElectrumX installed from existing installer."
    fi
  fi
  if ! command -v electrumx_server &>/dev/null; then
    if [ ! -d /root/electrumx-installer ]; then
      git clone https://github.com/MadCatMining/electrumx-installer.git /root/electrumx-installer
    fi
    set +e
    (cd /root/electrumx-installer && ./bootstrap.sh)
    bootstrap_ret=$?
    set -e
    if [ $bootstrap_ret -ne 0 ]; then
      echo "ElectrumX bootstrap failed (exit $bootstrap_ret). Check errors above."
      # Bootstrap often fails when ~/.electrumx-installer already exists; try running its install.sh
      if [ -x "$INSTALLER_HOME/.electrumx-installer/install.sh" ]; then
        echo "Running $INSTALLER_HOME/.electrumx-installer/install.sh ..."
        set +e
        "$INSTALLER_HOME/.electrumx-installer/install.sh"
        set -e
      fi
      if ! command -v electrumx_server &>/dev/null; then
        echo "Config will still be written. Install ElectrumX manually if needed."
      fi
    fi
  fi
  # Patch coins.py for Lynx (find site-packages path)
  COINS_PY="$(python3 -c "import electrumx.lib.coins as m; print(m.__file__.replace('__init__.py','coins.py'))" 2>/dev/null)" || true
  if [ -n "$COINS_PY" ] && [ -f "$COINS_PY" ]; then
    if ! grep -q "class Lynx(Coin):" "$COINS_PY"; then
      sed -i '/class Unitus(Coin):/Q' "$COINS_PY" 2>/dev/null || true
      cat >> "$COINS_PY" << 'COINSEOF'

# https://docs.getlynx.io/electrumx/
class Lynx(Coin):
    NAME = "Lynx"
    SHORTNAME = "LYNX"
    NET = "mainnet"
    P2PKH_VERBYTE = bytes.fromhex("2d")
    P2SH_VERBYTES = (bytes.fromhex("16"),)
    WIF_BYTE = bytes.fromhex("ad")
    GENESIS_HASH = ('984b30fc9bb5e5ff424ad7f4ec193053'
                    '8a7b14a2d93e58ad7976c23154ea4a76')
    DESERIALIZER = lib_tx.DeserializerSegWit
    TX_COUNT = 1
    TX_COUNT_HEIGHT = 1
    TX_PER_BLOCK = 1
    RPC_PORT = 9332
    PEER_DEFAULT_PORTS = {'t': '50004', 's': '50002'}
    PEERS = [
        'electrum5.getlynx.io s t',
        'electrum6.getlynx.io s t',
        'electrum7.getlynx.io s t',
        'electrum8.getlynx.io s t',
        'electrum9.getlynx.io s t',
    ]
    REORG_LIMIT = 5000
COINSEOF
    fi
  fi
fi

# DB directory
mkdir -p /db
chown electrumx:electrumx /db 2>/dev/null || true

# Build config
if [ -n "${ELECTRUMX_DOMAIN:-}" ]; then
  # SSL with Certbot
  if [ ! -d "/etc/letsencrypt/live/$ELECTRUMX_DOMAIN" ]; then
    apt-get install -y certbot 2>/dev/null || true
    certbot certonly --standalone -n -d "$ELECTRUMX_DOMAIN" -m "domains@getlynx.io" --agree-tos || true
    chown -R electrumx:electrumx /etc/letsencrypt 2>/dev/null || true
  fi
  cat > "$ELECTRUMX_CONF" << EOF
DB_DIRECTORY=/db
DAEMON_URL=http://${rpcuser}:${rpcpassword}@127.0.0.1:${rpcport}/
COIN=Lynx
DB_ENGINE=leveldb
COST_SOFT_LIMIT=0
COST_HARD_LIMIT=0
SSL_CERTFILE=/etc/letsencrypt/live/${ELECTRUMX_DOMAIN}/fullchain.pem
SSL_KEYFILE=/etc/letsencrypt/live/${ELECTRUMX_DOMAIN}/privkey.pem
SERVICES=ssl://:${ELECTRUMX_SSL_PORT},wss://:${ELECTRUMX_WSS_PORT},rpc://
REPORT_SERVICES=wss://${ELECTRUMX_DOMAIN}:${ELECTRUMX_WSS_PORT},ssl://${ELECTRUMX_DOMAIN}:${ELECTRUMX_SSL_PORT}
EOF
else
  # RPC only (no SSL)
  cat > "$ELECTRUMX_CONF" << EOF
DB_DIRECTORY=/db
DAEMON_URL=http://${rpcuser}:${rpcpassword}@127.0.0.1:${rpcport}/
COIN=Lynx
DB_ENGINE=leveldb
COST_SOFT_LIMIT=0
COST_HARD_LIMIT=0
SERVICES=rpc://
EOF
fi

# Ensure electrumx user exists (bootstrap may not create it)
if ! getent passwd electrumx &>/dev/null; then
  useradd -r -s /bin/false -d /db electrumx 2>/dev/null || true
  chown electrumx:electrumx /db 2>/dev/null || true
fi

# Create systemd unit if missing (bootstrap may not install it)
if [ ! -f /etc/systemd/system/electrumx.service ]; then
  ELECTRUMX_SERVER="$(command -v electrumx_server 2>/dev/null)" || true
  if [ -z "$ELECTRUMX_SERVER" ]; then
    for cand in /usr/local/bin/electrumx_server /root/electrumx-installer/venv/bin/electrumx_server; do
      if [ -x "$cand" ]; then
        ELECTRUMX_SERVER="$cand"
        break
      fi
    done
  fi
  if [ -z "$ELECTRUMX_SERVER" ]; then
    ELECTRUMX_SERVER="/usr/local/bin/electrumx_server"
  fi
  ELECTRUMX_RPC="$(command -v electrumx_rpc 2>/dev/null)" || true
  [ -z "$ELECTRUMX_RPC" ] && ELECTRUMX_RPC="/usr/local/bin/electrumx_rpc"
  cat > /etc/systemd/system/electrumx.service << UNITEOF
[Unit]
Description=ElectrumX
After=network.target

[Service]
EnvironmentFile=/etc/electrumx.conf
ExecStart=$ELECTRUMX_SERVER
ExecStop=$ELECTRUMX_RPC -p 8000 stop
User=electrumx
LimitNOFILE=8192
TimeoutStopSec=30min

[Install]
WantedBy=multi-user.target
UNITEOF
  systemctl daemon-reload
fi

systemctl enable electrumx 2>/dev/null || true
if ! systemctl restart electrumx 2>/dev/null && ! systemctl start electrumx 2>/dev/null; then
  echo "Could not start electrumx.service (unit may not exist yet). Config written to $ELECTRUMX_CONF"
  echo "Run: systemctl start electrumx   after the electrumx package is installed."
  exit 0
fi
echo "ElectrumX configured and started. Config: $ELECTRUMX_CONF"
