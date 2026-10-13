#!/usr/bin/env bash
# ==============================================================================
# Direct DiscoPanel Server Creator & Auto-Importer
# Creates a full server instance directly inside DiscoPanel (SQLite DB + Docker
# container + server_configs + mods index) from either:
#   1) A Converter URL or local .zip package:
#      curl -fsSL .../discopanel-import.sh | bash -s -- "<URL_OR_ZIP>" "Server Name" 6 25565 "fabric" "1.20.1"
#   2) Direct standalone server creation (no .zip required):
#      curl -fsSL .../discopanel-import.sh | bash -s -- --create "Server Name" "fabric" "1.20.1" 6 25565
# ==============================================================================

set -e

MODE="import"
if [ "$1" = "--create" ] || [ "$1" = "-c" ]; then
    MODE="create"
     shift
    CUSTOM_NAME="${1:-Minecraft Server}"
    ARG_LOADER="${2:-fabric}"
    ARG_MC_VER="${3:-1.20.1}"
    MEM_GB="${4:-6}"
    SERVER_PORT="${5:-25565}"
    ZIP_SOURCE=""
else
    ZIP_SOURCE="${1:-}"
    CUSTOM_NAME="${2:-}"
    MEM_GB="${3:-6}"
    SERVER_PORT="${4:-25565}"
    ARG_LOADER="${5:-}"
    ARG_MC_VER="${6:-}"
fi

DISCO_DATA="/opt/discopanel/data"
DISCO_DB="$DISCO_DATA/discopanel.db"
SERVERS_DIR="$DISCO_DATA/servers"
mkdir -p "$SERVERS_DIR"

SERVER_UUID=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || python3 -c "import uuid; print(uuid.uuid4())")
TEMP_EXTRACT="/tmp/discopanel_stage_$SERVER_UUID"
mkdir -p "$TEMP_EXTRACT"

# 1. Obtain and extract server package if provided
if [ "$MODE" = "import" ] && [ -n "$ZIP_SOURCE" ]; then
    if [[ "$ZIP_SOURCE" =~ ^https?:// ]]; then
        echo "==> Downloading converted server package from $ZIP_SOURCE ..."
        DOWNLOADED_ZIP="/tmp/discopanel_pack_${SERVER_UUID}.zip"
        curl -fL "$ZIP_SOURCE" -o "$DOWNLOADED_ZIP"
        echo "==> Extracting server files..."
        unzip -q -o "$DOWNLOADED_ZIP" -d "$TEMP_EXTRACT"
        rm -f "$DOWNLOADED_ZIP"
    elif [ -f "$ZIP_SOURCE" ]; then
        echo "==> Extracting local server package $ZIP_SOURCE ..."
        unzip -q -o "$ZIP_SOURCE" -d "$TEMP_EXTRACT"
    else
        echo "==> Note: '$ZIP_SOURCE' not found locally; creating clean DiscoPanel server instance directly..."
    fi
fi

# Flatten nested server/ directory if Dual Pack was passed
if [ -d "$TEMP_EXTRACT/server/mods" ] && [ ! -d "$TEMP_EXTRACT/mods" ]; then
    cp -rf "$TEMP_EXTRACT/server/"* "$TEMP_EXTRACT/" 2>/dev/null || true
    rm -rf "$TEMP_EXTRACT/server" "$TEMP_EXTRACT/client" "$TEMP_EXTRACT/curseforge" "$TEMP_EXTRACT/modrinth" 2>/dev/null || true
fi

# 2. Resolve Server Name, Loader, and Minecraft Version
SERVER_NAME="${CUSTOM_NAME:-Converted Server}"
if [ -z "$CUSTOM_NAME" ] && [ -f "$TEMP_EXTRACT/server.properties" ]; then
    PROP_MOTD=$(grep "^motd=" "$TEMP_EXTRACT/server.properties" | cut -d'=' -f2- | tr -d '\r')
    if [ -n "$PROP_MOTD" ]; then
        SERVER_NAME="$PROP_MOTD"
    fi
fi

LOADER="${ARG_LOADER:-}"
if [ -z "$LOADER" ]; then
    if grep -qi "neoforge" "$TEMP_EXTRACT/run.sh" "$TEMP_EXTRACT/CONVERSION_REPORT.txt" "$TEMP_EXTRACT/PACK_INFO.txt" 2>/dev/null; then
        LOADER="neoforge"
    elif grep -qi "forge" "$TEMP_EXTRACT/run.sh" "$TEMP_EXTRACT/CONVERSION_REPORT.txt" "$TEMP_EXTRACT/PACK_INFO.txt" 2>/dev/null; then
        LOADER="forge"
    elif grep -qi "quilt" "$TEMP_EXTRACT/run.sh" "$TEMP_EXTRACT/CONVERSION_REPORT.txt" "$TEMP_EXTRACT/PACK_INFO.txt" 2>/dev/null; then
        LOADER="quilt"
    else
        LOADER="fabric"
    fi
fi
LOADER_LOWER=$(echo "$LOADER" | tr '[:upper:]' '[:lower:]')
LOADER_UPPER=$(echo "$LOADER" | tr '[:lower:]' '[:upper:]')

MC_VER="${ARG_MC_VER:-}"
if [ -z "$MC_VER" ]; then
    if [ -f "$TEMP_EXTRACT/CONVERSION_REPORT.txt" ]; then
        MC_VER=$(grep "Minecraft Version:" "$TEMP_EXTRACT/CONVERSION_REPORT.txt" | awk '{print $3}' | tr -d '\r')
    elif [ -f "$TEMP_EXTRACT/PACK_INFO.txt" ]; then
        MC_VER=$(grep "Minecraft Version:" "$TEMP_EXTRACT/PACK_INFO.txt" | awk '{print $3}' | tr -d '\r')
    fi
fi
MC_VER="${MC_VER:-1.20.1}"

# 3. Create final DiscoPanel server directory (<safe_name>_<uuid>)
SAFE_NAME=$(echo "$SERVER_NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$//g')
SAFE_NAME="${SAFE_NAME:-mc-server}"
TARGET_DIR="$SERVERS_DIR/${SAFE_NAME}_${SERVER_UUID}"
mkdir -p "$TARGET_DIR/mods" "$TARGET_DIR/config"

cp -rf "$TEMP_EXTRACT/"* "$TARGET_DIR/" 2>/dev/null || true
rm -rf "$TEMP_EXTRACT"

echo "eula=true" > "$TARGET_DIR/eula.txt"
if [ ! -f "$TARGET_DIR/server.properties" ]; then
    cat <<EOF > "$TARGET_DIR/server.properties"
server-port=25565
motd=$SERVER_NAME
max-players=20
online-mode=true
difficulty=easy
gamemode=survival
view-distance=10
simulation-distance=8
allow-flight=true
prevent-proxy-connections=false
enable-rcon=true
rcon.port=25575
rcon.password=discopanel_${SERVER_UUID:0:8}
EOF
fi

# Ensure permissions for itzg/minecraft-server (UID 1000)
chown -R 1000:1000 "$TARGET_DIR" 2>/dev/null || chmod -R 777 "$TARGET_DIR"
chmod +x "$TARGET_DIR/run.sh" 2>/dev/null || true

# 4. Determine Optimal Java Version & Docker Image Tag for Minecraft Version
read -r JAVA_VER DOCKER_TAG <<< $(python3 - "$MC_VER" << 'PYEOF'
import sys, re
ver = sys.argv[1] if len(sys.argv) > 1 else "1.20.1"
parts = [int(x) for x in re.findall(r'\d+', ver)]
major = parts[0] if len(parts) > 0 else 1
minor = parts[1] if len(parts) > 1 else 20
patch = parts[2] if len(parts) > 2 else 0

if minor >= 21 or (minor == 20 and patch >= 5):
    print("21 java21")
elif minor >= 17:
    print("17 java17")
else:
    print("8 java8")
PYEOF
)

MEM_MB=$((MEM_GB * 1024))
INIT_MEM_M=$((MEM_MB * 45 / 100))
MAX_MEM_M=$((MEM_MB * 75 / 100))
RCON_PASSWORD="discopanel_${SERVER_UUID:0:8}"
RCON_HOST_PORT=$((SERVER_PORT + 10))
CONTAINER_NAME="discopanel-server-$SERVER_UUID"

echo "================================================================="
echo " Creating Server Directly in DiscoPanel"
echo "-----------------------------------------------------------------"
echo " Server ID:  $SERVER_UUID"
echo " Name:       $SERVER_NAME"
echo " Loader:     $LOADER_UPPER ($LOADER_LOWER)"
echo " MC Version: $MC_VER (Java $JAVA_VER / itzg:$DOCKER_TAG)"
echo " Memory:     ${MEM_GB} GB (${MEM_MB} MB)"
echo " Game Port:  $SERVER_PORT (RCON: 127.0.0.1:$RCON_HOST_PORT)"
echo " Data Path:  $TARGET_DIR"
echo "================================================================="

# 5. Ensure DiscoPanel Docker network exists & free conflicting port if needed
docker network inspect discopanel-network >/dev/null 2>&1 || docker network create discopanel-network >/dev/null 2>&1 || true

CONFLICT_CONTAINERS=$(docker ps --format '{{.ID}} {{.Ports}}' | grep ":${SERVER_PORT}->" | awk '{print $1}' || true)
for cid in $CONFLICT_CONTAINERS; do
    echo "==> Stopping existing container ($cid) using port $SERVER_PORT..."
    docker stop "$cid" >/dev/null 2>&1 || true
done

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

# 6. Create & Start DiscoPanel-Managed Docker Container
docker run -d -t -i \
  --name "$CONTAINER_NAME" \
  --network discopanel-network \
  --restart unless-stopped \
  --memory "${MEM_MB}m" \
  --memory-swap "${MEM_MB}m" \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  --label "discopanel.server.id=$SERVER_UUID" \
  --label "discopanel.server.name=$SERVER_NAME" \
  --label "discopanel.server.loader=$LOADER_LOWER" \
  --label "discopanel.server.version=$MC_VER" \
  --label "discopanel.managed=true" \
  -p "${SERVER_PORT}:25565/tcp" \
  -p "127.0.0.1:${RCON_HOST_PORT}:25575/tcp" \
  -v "${TARGET_DIR}:/data" \
  -e UID=1000 \
  -e GID=1000 \
  -e EULA=TRUE \
  -e TYPE="$LOADER_UPPER" \
  -e VERSION="$MC_VER" \
  -e MEMORY="${MEM_MB}M" \
  -e INIT_MEMORY="${INIT_MEM_M}M" \
  -e MAX_MEMORY="${MAX_MEM_M}M" \
  -e USE_AIKAR_FLAGS=true \
  -e MOTD="$SERVER_NAME" \
  -e SERVER_NAME="$SERVER_NAME" \
  -e SERVER_PORT=25565 \
  -e MAX_PLAYERS=20 \
  -e DIFFICULTY=easy \
  -e MODE=survival \
  -e ALLOW_FLIGHT=true \
  -e ONLINE_MODE=true \
  -e PREVENT_PROXY_CONNECTIONS=false \
  -e ENABLE_RCON=true \
  -e RCON_PASSWORD="$RCON_PASSWORD" \
  -e RCON_PORT=25575 \
  "itzg/minecraft-server:${DOCKER_TAG}" >/dev/null

FULL_CONTAINER_ID=$(docker inspect -f '{{.Id}}' "$CONTAINER_NAME" 2>/dev/null || echo "")

# 7. Register Server, ServerConfig, and Mods in DiscoPanel SQLite DB (/opt/discopanel/data/discopanel.db)
if [ -f "$DISCO_DB" ]; then
    echo "==> Registering server in DiscoPanel database ($DISCO_DB)..."
    systemctl stop discopanel 2>/dev/null || true

    python3 - "$DISCO_DB" "$SERVER_UUID" "$SERVER_NAME" "$LOADER_LOWER" "$LOADER_UPPER" "$MC_VER" "$FULL_CONTAINER_ID" "$SERVER_PORT" "$MEM_MB" "$INIT_MEM_M" "$MAX_MEM_M" "$JAVA_VER" "$DOCKER_TAG" "$TARGET_DIR" "$RCON_PASSWORD" << 'PYEOF'
import sys, os, sqlite3, uuid
from datetime import datetime, timezone

(
    db_path,
    server_uuid,
    server_name,
    loader_lower,
    loader_upper,
    mc_ver,
    container_id,
    server_port,
    mem_mb,
    init_mem_m,
    max_mem_m,
    java_ver,
    docker_tag,
    target_dir,
    rcon_password,
) = sys.argv[1:16]

now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f+00:00")
tps_cmd = "forge tps" if loader_lower in ("forge", "neoforge") else "spark tps"

conn = sqlite3.connect(db_path)
cur = conn.cursor()

def get_columns(table_name):
    cur.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cur.fetchall()}

def insert_filtered(table_name, data_dict):
    cols = get_columns(table_name)
    if not cols:
        return
    filtered = {k: v for k, v in data_dict.items() if k in cols}
    col_names = ", ".join(filtered.keys())
    placeholders = ", ".join(["?"] * len(filtered))
    sql = f"INSERT OR REPLACE INTO {table_name} ({col_names}) VALUES ({placeholders})"
    cur.execute(sql, list(filtered.values()))

# If an existing non-proxied server in DB holds the same port, bump its port in DB so unique checks pass
server_cols = get_columns("servers")
if "port" in server_cols:
    cur.execute("UPDATE servers SET status = 'stopped' WHERE port = ? AND id != ?", (int(server_port), server_uuid))

# 1. Insert into servers
insert_filtered("servers", {
    "id": server_uuid,
    "name": server_name,
    "description": f"Created by MC Server Converter ({loader_upper} {mc_ver})",
    "mod_loader": loader_lower,
    "mc_version": mc_ver,
    "container_id": container_id,
    "status": "running",
    "port": int(server_port),
    "proxy_port": 0,
    "proxy_hostname": "",
    "proxy_listener_id": "",
    "max_players": 20,
    "memory": int(mem_mb),
    "created_at": now_iso,
    "updated_at": now_iso,
    "last_started": now_iso,
    "java_version": str(java_ver),
    "docker_image": docker_tag,
    "data_path": target_dir,
    "detached": 0,
    "auto_start": 1,
    "tps_command": tps_cmd,
    "additional_ports": "[]",
    "docker_overrides": "{}",
})

# 2. Insert into server_configs
insert_filtered("server_configs", {
    "id": f"{server_uuid}-config",
    "server_id": server_uuid,
    "updated_at": now_iso,
    "uid": 1000,
    "gid": 1000,
    "memory": f"{mem_mb}M",
    "init_memory": f"{init_mem_m}M",
    "max_memory": f"{max_mem_m}M",
    "tz": "UTC",
    "use_aikar_flags": 1,
    "type": loader_upper,
    "eula": "TRUE",
    "version": mc_ver,
    "motd": server_name,
    "difficulty": "easy",
    "mode": "survival",
    "max_players": 20,
    "allow_nether": 1,
    "announce_player_achievements": 1,
    "generate_structures": 1,
    "level": "world",
    "online_mode": 1,
    "allow_flight": 1,
    "server_name": server_name,
    "server_port": int(server_port),
    "sync_chunk_writes": 1,
    "enable_status": 1,
    "prevent_proxy_connections": 0,
    "use_native_transport": 1,
    "enable_query": 1,
    "query_port": int(server_port),
    "broadcast_console_to_ops": 1,
    "enforce_secure_profile": 0,
    "log_ips": 1,
    "enable_rcon": 1,
    "rcon_password": rcon_password,
    "rcon_port": 25575,
})

# 3. Index all server mods into mods table so they appear in DiscoPanel's Mods UI
mods_dir = os.path.join(target_dir, "mods")
if os.path.isdir(mods_dir) and get_columns("mods"):
    for fname in sorted(os.listdir(mods_dir)):
        if not fname.endswith(".jar"):
            continue
        fpath = os.path.join(mods_dir, fname)
        mod_title = fname[:-4]
        insert_filtered("mods", {
            "id": str(uuid.uuid4()),
            "server_id": server_uuid,
            "name": mod_title,
            "file_name": fname,
            "version": mc_ver,
            "mod_id": mod_title.lower(),
            "description": "Imported server mod",
            "enabled": 1,
            "uploaded_at": now_iso,
            "file_size": os.path.getsize(fpath),
        })

conn.commit()
conn.close()
print("==> Successfully registered server and mods in DiscoPanel DB.")
PYEOF

    systemctl start discopanel 2>/dev/null || true
else
    systemctl restart discopanel 2>/dev/null || true
fi

MOD_COUNT=$(find "$TARGET_DIR/mods" -maxdepth 1 -name "*.jar" 2>/dev/null | wc -l)

echo "================================================================="
echo " [✔] Server Created & Running in DiscoPanel!"
echo "-----------------------------------------------------------------"
echo " DiscoPanel UI:  http://192.168.0.119:8080/servers/$SERVER_UUID"
echo " Container:      $CONTAINER_NAME"
echo " Server Mods:    $MOD_COUNT .jar files indexed"
echo " Connect Port:   $SERVER_PORT"
echo "================================================================="
