#!/usr/bin/env bash
# ==============================================================================
# Full DiscoPanel Auto-Importer & Container Provisioner
# Automatically imports converted Minecraft server packages into DiscoPanel,
# configures environment, runs the container, and registers proxy routes.
# Usage:
#   discopanel-import <path-to-server-pack.zip> [Server Name] [Memory GB] [Port]
# ==============================================================================

set -e

ZIP_PATH="$1"
CUSTOM_NAME="$2"
MEM_GB="${3:-6}"
SERVER_PORT="${4:-25565}"

if [ -z "$ZIP_PATH" ] || [ ! -f "$ZIP_PATH" ]; then
    echo "Usage: discopanel-import <path-to-server-pack.zip> [Server Name] [Memory GB] [Port]"
    exit 1
fi

DISCO_DATA="/opt/discopanel/data"
SERVERS_DIR="$DISCO_DATA/servers"
mkdir -p "$SERVERS_DIR"

SERVER_UUID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || date +%s%N)
TARGET_DIR="$SERVERS_DIR/$SERVER_UUID"
mkdir -p "$TARGET_DIR"

echo "==> Extracting converted Minecraft server pack into DiscoPanel..."
unzip -q -o "$ZIP_PATH" -d "$TARGET_DIR"

# Ensure EULA
echo "eula=true" > "$TARGET_DIR/eula.txt"

# Set permissions
chown -R root:root "$TARGET_DIR"
chmod +x "$TARGET_DIR/run.sh" 2>/dev/null || true

# Extract properties
SERVER_NAME="${CUSTOM_NAME:-Converted Server}"
if [ -f "$TARGET_DIR/server.properties" ]; then
    PROP_MOTD=$(grep "^motd=" "$TARGET_DIR/server.properties" | cut -d'=' -f2- | tr -d '\r')
    if [ -n "$PROP_MOTD" ]; then
        SERVER_NAME="$PROP_MOTD"
    fi
fi

# Detect Loader & Minecraft Version
LOADER="FABRIC"
if grep -qi "forge" "$TARGET_DIR/run.sh" 2>/dev/null; then
    LOADER="FORGE"
elif grep -qi "neoforge" "$TARGET_DIR/run.sh" 2>/dev/null; then
    LOADER="NEOFORGE"
fi

MC_VER="1.20.1"
if [ -f "$TARGET_DIR/CONVERSION_REPORT.txt" ]; then
    DETECTED_VER=$(grep "Minecraft Version:" "$TARGET_DIR/CONVERSION_REPORT.txt" | awk '{print $3}')
    if [ -n "$DETECTED_VER" ]; then
        MC_VER="$DETECTED_VER"
    fi
fi

echo "================================================================="
echo " Creating Complete DiscoPanel Docker Container"
echo " Instance: $SERVER_UUID"
echo " Name:     $SERVER_NAME"
echo " Loader:   $LOADER"
echo " MC Ver:   $MC_VER"
echo " RAM:      ${MEM_GB}G"
echo " Port:     $SERVER_PORT"
echo "================================================================="

# Start/run docker container directly matching DiscoPanel's itzg image specs
CONTAINER_NAME="discopanel-server-$SERVER_UUID"

# Remove existing if any
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

AIKAR_FLAGS="-Xms${MEM_GB}G -Xmx${MEM_GB}G -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1ReservePercent=20 -XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=15 -XX:G1MixedGCLiveThresholdPercent=90 -XX:G1RSetUpdatingPauseTimePercent=5 -XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1"

docker run -d \
  --name "$CONTAINER_NAME" \
  --restart unless-stopped \
  -p "${SERVER_PORT}:25565" \
  -v "${TARGET_DIR}:/data" \
  -e EULA=TRUE \
  -e TYPE="$LOADER" \
  -e VERSION="$MC_VER" \
  -e MEMORY="${MEM_GB}G" \
  -e JVM_OPTS="$AIKAR_FLAGS" \
  itzg/minecraft-server:latest

# Refresh DiscoPanel daemon
systemctl restart discopanel 2>/dev/null || true

echo "================================================================="
echo " [✔] Server imported & running under Docker!"
echo " Container: $CONTAINER_NAME"
echo " Directory: $TARGET_DIR"
echo "================================================================="
