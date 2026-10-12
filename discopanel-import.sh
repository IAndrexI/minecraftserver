#!/usr/bin/env bash
# ==============================================================================
# DiscoPanel Auto-Importer Helper
# Automatically imports converted Minecraft server packages into DiscoPanel.
# Usage:
#   discopanel-import <path-to-server-pack.zip> [Server Name]
# ==============================================================================

set -e

ZIP_PATH="$1"
CUSTOM_NAME="$2"

if [ -z "$ZIP_PATH" ] || [ ! -f "$ZIP_PATH" ]; then
    echo "Usage: discopanel-import <path-to-server-pack.zip> [Optional Server Name]"
    exit 1
fi

DISCO_DATA="/opt/discopanel/data"
SERVERS_DIR="$DISCO_DATA/servers"

if [ ! -d "$SERVERS_DIR" ]; then
    mkdir -p "$SERVERS_DIR"
fi

# Generate unique server ID
SERVER_UUID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || date +%s%N)
TARGET_DIR="$SERVERS_DIR/$SERVER_UUID"

echo "==> Creating DiscoPanel Server Instance: $SERVER_UUID"
mkdir -p "$TARGET_DIR"

echo "==> Extracting converted server pack into DiscoPanel..."
unzip -q -o "$ZIP_PATH" -d "$TARGET_DIR"

# Ensure permissions
chown -R root:root "$TARGET_DIR"
chmod +x "$TARGET_DIR/run.sh" 2>/dev/null || true

echo "==> Server files placed into DiscoPanel directory: $TARGET_DIR"

# Read properties if available
MC_NAME="${CUSTOM_NAME:-Converted Server}"
if [ -f "$TARGET_DIR/server.properties" ]; then
    PROP_MOTD=$(grep "^motd=" "$TARGET_DIR/server.properties" | cut -d'=' -f2- | tr -d '\r')
    if [ -n "$PROP_MOTD" ]; then
        MC_NAME="$PROP_MOTD"
    fi
fi

echo "================================================================="
echo " [✔] Server files successfully imported into DiscoPanel!"
echo " Server Directory: $TARGET_DIR"
echo " Restarting DiscoPanel service to index new instance..."
echo "================================================================="

systemctl restart discopanel 2>/dev/null || true
echo "Done! Check your DiscoPanel web dashboard."
