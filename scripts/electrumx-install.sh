#!/bin/bash
# ElectrumX install for Beacon: uses existing Lynx node at LYNX_WORKING_DIR.
# Prompts for ELECTRUMX_DOMAIN (or set env) for SSL cert paths; config uses Cloudflare Origin Cert.
# Set REINSTALL_ELECTRUMX=1 to update ElectrumX and reset coins.py + /etc/electrumx.conf.
set -euo pipefail

REINSTALL_ELECTRUMX="${REINSTALL_ELECTRUMX:-0}"
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

# RPC from lynx.conf: use only mainnet (main.*) values; ignore testnet (test.*)
rpcuser="$(sed -ne 's|[ \t]*main\.rpcuser=[ \t]*||p' "$LYNX_CONF" | tr -d '\r' | head -n1)"
rpcpassword="$(sed -ne 's|[ \t]*main\.rpcpassword=[ \t]*||p' "$LYNX_CONF" | tr -d '\r' | head -n1)"
rpcport="$(sed -ne 's|[ \t]*main\.rpcport=[ \t]*||p' "$LYNX_CONF" | tr -d '\r' | head -n1)"
# Fallback for lynx.conf with unprefixed keys (older format)
[ -z "$rpcuser" ] && rpcuser="$(sed -ne 's|[ \t]*rpcuser=[ \t]*||p' "$LYNX_CONF" | tr -d '\r' | head -n1)"
[ -z "$rpcpassword" ] && rpcpassword="$(sed -ne 's|[ \t]*rpcpassword=[ \t]*||p' "$LYNX_CONF" | tr -d '\r' | head -n1)"
[ -z "$rpcport" ] && rpcport="$(sed -ne 's|[ \t]*rpcport=[ \t]*||p' "$LYNX_CONF" | tr -d '\r' | head -n1)"
rpcport="${rpcport:-9332}"

if [ -z "$rpcuser" ] || [ -z "$rpcpassword" ]; then
  echo "Could not read main.rpcuser/main.rpcpassword (or rpcuser/rpcpassword) from $LYNX_CONF"
  exit 1
fi

# Install or reinstall ElectrumX via MadCatMining electrumx-installer only (PyPI version is not compatible with Lynx)
INSTALLER_HOME="${SUDO_HOME:-$HOME}"
[ -z "$INSTALLER_HOME" ] && INSTALLER_HOME="/root"
DO_INSTALL=false
if [ "$REINSTALL_ELECTRUMX" = "1" ]; then
  DO_INSTALL=true
elif ! command -v electrumx_server &>/dev/null; then
  DO_INSTALL=true
fi

if [ "$DO_INSTALL" = true ]; then
  ALREADY_INSTALLED=false
  command -v electrumx_server &>/dev/null && ALREADY_INSTALLED=true

  if [ "$ALREADY_INSTALLED" = true ] && [ "$REINSTALL_ELECTRUMX" = "1" ]; then
    echo "Reinstalling/updating ElectrumX (will reset /etc/electrumx.conf and re-apply Lynx patch to coins.py)..."
    set +e
    if [ -x "$INSTALLER_HOME/.electrumx-installer/install.sh" ]; then
      "$INSTALLER_HOME/.electrumx-installer/install.sh" --update 2>/dev/null || "$INSTALLER_HOME/.electrumx-installer/install.sh"
    elif [ -d /root/electrumx-installer ]; then
      (cd /root/electrumx-installer && ./bootstrap.sh --update 2>/dev/null) || (cd /root/electrumx-installer && ./bootstrap.sh)
    else
      if [ ! -d /root/electrumx-installer ]; then
        git clone https://github.com/MadCatMining/electrumx-installer.git /root/electrumx-installer
      fi
      (cd /root/electrumx-installer && ./bootstrap.sh --update 2>/dev/null) || (cd /root/electrumx-installer && ./bootstrap.sh)
    fi
    set -e
  else
    # First-time install
    echo "Installing ElectrumX via https://github.com/MadCatMining/electrumx-installer ..."
    apt-get update -y
    set +e
    apt-get install -y git python3-pip gcc g++ build-essential \
      libsnappy-dev zlib1g-dev libbz2-dev liblz4-dev libzstd-dev librocksdb-dev
    apt_ret=$?
    set -e
    if [ $apt_ret -ne 0 ]; then
      echo "apt-get install had errors (exit $apt_ret). Trying optional packages separately..."
      apt-get install -y librocksdb-dev 2>/dev/null || true
    fi
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
  fi

  # Patch coins.py for Lynx (first install or reinstall; re-apply after update so coins.py is reset then patched)
  COINS_PY="$(python3 -c "import electrumx.lib.coins as m; print(m.__file__.replace('__init__.py','coins.py'))" 2>/dev/null)" || true
  if [ -n "$COINS_PY" ] && [ -f "$COINS_PY" ]; then
    if ! grep -q "class Lynx(Coin):" "$COINS_PY"; then
      sed -i '/class Unitus(Coin):/Q' "$COINS_PY" 2>/dev/null || true
      cat >> "$COINS_PY" << 'COINSEOF'

from . import lib_tx
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
      echo "Lynx coin support patched into ElectrumX."
    fi
  fi
fi

# DB directory
mkdir -p /db
chown electrumx:electrumx /db 2>/dev/null || true

# Domain for SSL is required (e.g. electrum8.getlynx.io); used for cert paths and REPORT_SERVICES
if [ -z "${ELECTRUMX_DOMAIN:-}" ]; then
  if [ -t 0 ]; then
    echo ""
    read -rp "Enter domain name for ElectrumX SSL (e.g. electrum8.getlynx.io): " ELECTRUMX_DOMAIN
    ELECTRUMX_DOMAIN="${ELECTRUMX_DOMAIN// /}"
  fi
  if [ -z "${ELECTRUMX_DOMAIN:-}" ]; then
    echo "ElectrumX domain is required. Set ELECTRUMX_DOMAIN or enter it when prompted. Aborting."
    exit 1
  fi
fi

# Create cert directory so user can place Cloudflare Origin Cert files (fullchain.pem, privkey.pem)
CERT_DIR="/etc/letsencrypt/live/${ELECTRUMX_DOMAIN}"
mkdir -p "$CERT_DIR"
chown electrumx:electrumx /etc/letsencrypt 2>/dev/null || true
chown -R electrumx:electrumx "$CERT_DIR" 2>/dev/null || true

# Config always uses SSL block; user must add Cloudflare 15-Year Origin Cert to the two .pem paths
cat > "$ELECTRUMX_CONF" << EOF
DB_DIRECTORY=/db
DAEMON_URL=http://${rpcuser}:${rpcpassword}@127.0.0.1:${rpcport}/
COIN=Lynx
DB_ENGINE=rocksdb
COST_SOFT_LIMIT=0
COST_HARD_LIMIT=0
SSL_CERTFILE=${CERT_DIR}/fullchain.pem
SSL_KEYFILE=${CERT_DIR}/privkey.pem
SERVICES=ssl://:${ELECTRUMX_SSL_PORT},wss://:${ELECTRUMX_WSS_PORT},rpc://
REPORT_SERVICES=wss://${ELECTRUMX_DOMAIN}:${ELECTRUMX_WSS_PORT},ssl://${ELECTRUMX_DOMAIN}:${ELECTRUMX_SSL_PORT}
HOST=
EOF

echo ""
echo "--- ElectrumX SSL: Cloudflare 15-Year Origin Certificate ---"
echo "To enable SSL, create a 15-Year Origin Certificate in Cloudflare (SSL/TLS -> Origin Server)."
echo "Then copy the certificate and private key into:"
echo "  Certificate: $CERT_DIR/fullchain.pem"
echo "  Private key: $CERT_DIR/privkey.pem"
echo "Ensure the electrumx user can read both files (e.g. chown electrumx:electrumx $CERT_DIR/*.pem)."
echo "----------------------------------------------------------------"
echo ""

# Ensure electrumx user exists (bootstrap may not create it)
if ! getent passwd electrumx &>/dev/null; then
  useradd -r -s /bin/false -d /db electrumx 2>/dev/null || true
  chown electrumx:electrumx /db 2>/dev/null || true
fi

# Resolve electrumx_server / electrumx_rpc (from MadCatMining installer venv or PATH)
ELECTRUMX_SERVER="$(command -v electrumx_server 2>/dev/null)" || true
if [ -z "$ELECTRUMX_SERVER" ]; then
  for cand in /usr/local/bin/electrumx_server /root/electrumx-installer/venv/bin/electrumx_server /root/.electrumx-installer/venv/bin/electrumx_server; do
    if [ -x "$cand" ]; then
      ELECTRUMX_SERVER="$cand"
      break
    fi
  done
fi
[ -z "$ELECTRUMX_SERVER" ] && ELECTRUMX_SERVER="/usr/local/bin/electrumx_server"
ELECTRUMX_RPC="$(command -v electrumx_rpc 2>/dev/null)" || true
if [ -z "$ELECTRUMX_RPC" ]; then
  for cand in /usr/local/bin/electrumx_rpc /root/electrumx-installer/venv/bin/electrumx_rpc /root/.electrumx-installer/venv/bin/electrumx_rpc; do
    if [ -x "$cand" ]; then
      ELECTRUMX_RPC="$cand"
      break
    fi
  done
fi
[ -z "$ELECTRUMX_RPC" ] && ELECTRUMX_RPC="/usr/local/bin/electrumx_rpc"

# Create or fix systemd unit: always recreate when we just updated ElectrumX, or when unit is missing / ExecStart is broken
NEED_UNIT_WRITE=false
if [ "$REINSTALL_ELECTRUMX" = "1" ]; then
  NEED_UNIT_WRITE=true
elif [ ! -f /etc/systemd/system/electrumx.service ]; then
  NEED_UNIT_WRITE=true
elif [ -x "$ELECTRUMX_SERVER" ]; then
  CURRENT_EXEC="$(grep '^ExecStart=' /etc/systemd/system/electrumx.service 2>/dev/null | sed 's/^ExecStart=//')"
  if [ -n "$CURRENT_EXEC" ] && [ ! -x "$CURRENT_EXEC" ]; then
    NEED_UNIT_WRITE=true
  fi
fi
if [ "$NEED_UNIT_WRITE" = true ] && [ -x "$ELECTRUMX_SERVER" ]; then
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
