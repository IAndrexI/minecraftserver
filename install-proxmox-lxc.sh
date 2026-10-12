#!/usr/bin/env bash
# Proxmox VE Helper Script - Minecraft Server Converter LXC Installer
# Source: https://github.com/IAndrexI/minecraftserver

set -e

# Visual colors
YW=$(echo "\033[33m")
BL=$(echo "\033[36m")
RD=$(echo "\033[01;31m")
BGN=$(echo "\033[4;92m")
GN=$(echo "\033[1;92m")
DGN=$(echo "\033[32m")
CL=$(echo "\033[m")

echo -e "${BL}
   __  ___ _____   _____                          
  /  |/  // ___/  / ___/___  ______   _____  _____
 / /|_/ / \__ \   \__ \/ _ \/ ___/ | / / _ \/ ___/
/ /  / / ___/ /  ___/ /  __/ /   | |/ /  __/ /    
/_/  /_//____/  /____/\___/_/    |___/\___/_/     
${CL}"
echo -e "${GN}Minecraft Modpack to Server Converter - Proxmox LXC Setup${CL}\n"

# Verify running on Proxmox
if [ ! -f /etc/pve/pve-root-ca.pem ]; then
    echo -e "${RD}[!] Error: This script must be run directly on a Proxmox VE host.${CL}"
    exit 1
fi

NEXTID=$(pvesh get /cluster/nextid)
read -p "Enter Container ID [Default: $NEXTID]: " CTID
CTID=${CTID:-$NEXTID}

read -p "Enter Container Hostname [Default: mc-converter]: " HN
HN=${HN:-mc-converter}

read -p "Enter Disk Size in GB [Default: 8]: " DISK
DISK=${DISK:-8}

read -p "Enter RAM in MB [Default: 2048]: " RAM
RAM=${RAM:-2048}

read -p "Enter Cores [Default: 2]: " CORES
CORES=${CORES:-2}

# Get default storage
STORAGE=$(pvesm status -content rootdir | awk 'NR>1 {print $1}' | head -n1)
read -p "Enter Storage Pool [Default: $STORAGE]: " USER_STORAGE
STORAGE=${USER_STORAGE:-$STORAGE}

# Get default bridge
BRIDGE="vmbr0"

echo -e "\n${BL}[*] Downloading Debian 12 standard template...${CL}"
pveam update >/dev/null 2>&1
TEMPLATE=$(pveam list local | grep debian-12-standard | awk '{print $1}' | head -n1)

if [ -z "$TEMPLATE" ]; then
    pveam download local debian-12-standard_12.7-1_amd64.tar.zst >/dev/null 2>&1 || true
    TEMPLATE=$(pveam list local | grep debian-12-standard | awk '{print $1}' | head -n1)
fi

echo -e "${BL}[*] Creating LXC Container $CTID ($HN)...${CL}"
pct create $CTID $TEMPLATE \
    --hostname $HN \
    --cores $CORES \
    --memory $RAM \
    --swap 512 \
    --features nesting=1 \
    --ostype debian \
    --rootfs $STORAGE:$DISK \
    --net0 name=eth0,bridge=$BRIDGE,ip=dhcp \
    --onboot 1 \
    --unprivileged 1

echo -e "${BL}[*] Starting Container $CTID...${CL}"
pct start $CTID
sleep 6

echo -e "${BL}[*] Provisioning Dependencies & MC Converter Service...${CL}"
pct exec $CTID -- bash -c "
    apt-get update -y >/dev/null 2>&1
    apt-get install -y git python3 python3-pip python3-venv curl >/dev/null 2>&1
    
    mkdir -p /opt/mc-converter
    git clone https://github.com/IAndrexI/minecraftserver.git /opt/mc-converter >/dev/null 2>&1
    
    cd /opt/mc-converter
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip >/dev/null 2>&1
    ./venv/bin/pip install -r requirements.txt >/dev/null 2>&1

    cat <<'EOF' >/etc/systemd/system/mc-converter.service
[Unit]
Description=Minecraft Modpack Server Converter Web Service
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mc-converter
ExecStart=/opt/mc-converter/venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    systemctl enable --now mc-converter.service >/dev/null 2>&1
"

# Get IP of the container
IP=$(pct exec $CTID -- hostname -I | awk '{print $1}')

echo -e "\n${GN}======================================================${CL}"
echo -e "${GN} [✔] Installation Completed Successfully!${CL}"
echo -e "${GN}======================================================${CL}"
echo -e "${BL}Access the Web Converter Dashboard at:${CL}"
echo -e "   ${BGN}http://$IP:8080${CL}\n"
