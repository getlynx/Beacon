 #!/bin/bash
 
 set -euo pipefail
 
INSTALL_DIR="/usr/local/beacon"
INSTALLER_URL="https://github.com/getlynx/Beacon/releases/latest/download/installer.sh"
 INSTALLER_PATH="${INSTALL_DIR}/installer.sh"
 
 if [ "$EUID" -ne 0 ]; then
   echo "Please run as root: sudo bash -c \"wget -qO- ${INSTALLER_URL} | bash\""
   exit 1
 fi
 
 mkdir -p "$INSTALL_DIR"
 
 if command -v curl >/dev/null 2>&1; then
   curl -fsSL "$INSTALLER_URL" -o "$INSTALLER_PATH"
 elif command -v wget >/dev/null 2>&1; then
   wget -qO "$INSTALLER_PATH" "$INSTALLER_URL"
 else
   echo "curl or wget is required to download the installer."
   exit 1
 fi
 
 chmod +x "$INSTALLER_PATH"
 echo "Running installer..."
 "$INSTALLER_PATH"
