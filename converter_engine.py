"""
Core modpack parsing, side-detection, and server file generation engine.
"""

import os
import io
import re
import json
import zipfile
import shutil
import logging
import requests
from typing import Dict, List, Tuple, Optional, Any
from converter_catalog import KNOWN_CLIENT_MODS, SERVER_PERFORMANCE_CATALOG

logger = logging.getLogger("mc-converter")

MODRINTH_API_BASE = "https://api.modrinth.com/v2"

class ModpackAnalysis:
    def __init__(self):
        self.pack_name: str = "Custom Server Pack"
        self.minecraft_version: str = "1.20.1"
        self.loader: str = "fabric"  # fabric, forge, neoforge, quilt
        self.loader_version: str = ""
        self.client_mods_removed: List[Dict[str, str]] = []
        self.server_mods_kept: List[Dict[str, str]] = []
        self.recommended_performance_mods: List[Dict[str, Any]] = []
        self.raw_manifest: Optional[Dict[str, Any]] = None
        self.pack_type: str = "unknown"  # curseforge, modrinth, generic_zip

def sanitize_id(name: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '', name.lower())
    cleaned = re.sub(r'[-_](fabric|forge|neoforge|quilt|mc[0-9.]+|v?[0-9.]+).*', '', cleaned)
    return cleaned

def inspect_jar_metadata(jar_data: bytes, filename: str) -> Tuple[str, str, str]:
    """
    Inspects inside a JAR without extracting to disk.
    Returns: (mod_id, display_name, environment)
    environment can be 'client', 'server', or '*'
    """
    mod_id = sanitize_id(os.path.splitext(filename)[0])
    name = filename
    environment = "*"

    try:
        with zipfile.ZipFile(io.BytesIO(jar_data)) as z:
            # 1. Check Fabric: fabric.mod.json
            if "fabric.mod.json" in z.namelist():
                try:
                    meta = json.loads(z.read("fabric.mod.json").decode('utf-8', errors='ignore'))
                    mod_id = meta.get("id", mod_id)
                    name = meta.get("name", name)
                    env = meta.get("environment", "*")
                    if env in ["client", "server"]:
                        environment = env
                except Exception as e:
                    logger.debug(f"Error parsing fabric.mod.json in {filename}: {e}")

            # 2. Check Quilt: quilt.mod.json
            elif "quilt.mod.json" in z.namelist():
                try:
                    meta = json.loads(z.read("quilt.mod.json").decode('utf-8', errors='ignore'))
                    quilt_loader = meta.get("quilt_loader", {})
                    mod_id = quilt_loader.get("id", mod_id)
                    metadata = quilt_loader.get("metadata", {})
                    name = metadata.get("name", name)
                    env = quilt_loader.get("environment", "*")
                    if env in ["client", "server"]:
                        environment = env
                except Exception:
                    pass

            # 3. Check Forge / NeoForge: META-INF/mods.toml or neoforge.mods.toml
            for toml_path in ["META-INF/mods.toml", "META-INF/neoforge.mods.toml"]:
                if toml_path in z.namelist():
                    content = z.read(toml_path).decode('utf-8', errors='ignore')
                    # Look for displayTest or clientSideOnly
                    if 'displayTest="IGNORE_SERVER_VERSION"' in content or 'displayTest="NONE"' in content or 'clientSideOnly=true' in content:
                        environment = "client"
                    
                    id_match = re.search(r'modId\s*=\s*["\']([^"\']+)["\']', content)
                    if id_match:
                        mod_id = id_match.group(1)
                    name_match = re.search(r'displayName\s*=\s*["\']([^"\']+)["\']', content)
                    if name_match:
                        name = name_match.group(1)
                    break

    except Exception as e:
        logger.debug(f"Failed to inspect zip internals for {filename}: {e}")

    # Fallback to known client mod database
    norm_id = mod_id.lower().replace("-", "").replace("_", "")
    for known in KNOWN_CLIENT_MODS:
        known_norm = known.replace("-", "").replace("_", "")
        if known_norm in norm_id or norm_id in known_norm:
            environment = "client"
            break

    return mod_id, name, environment

def query_modrinth_version(project_slug: str, mc_version: str, loader: str) -> Optional[Dict[str, str]]:
    """Fetches compatible file download for a server-side mod from Modrinth API."""
    try:
        url = f"{MODRINTH_API_BASE}/project/{project_slug}/version"
        params = {
            "game_versions": json.dumps([mc_version]),
            "loaders": json.dumps([loader])
        }
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            versions = res.json()
            if versions:
                primary_file = versions[0]["files"][0]
                return {
                    "filename": primary_file["filename"],
                    "url": primary_file["url"],
                    "version_number": versions[0]["version_number"]
                }
    except Exception as e:
        logger.warning(f"Modrinth lookup failed for {project_slug}: {e}")
    return None

def analyze_modpack(file_bytes: bytes, original_filename: str) -> Tuple[ModpackAnalysis, zipfile.ZipFile]:
    analysis = ModpackAnalysis()
    archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    namelist = archive.namelist()

    # Determine pack type
    if "manifest.json" in namelist:
        analysis.pack_type = "curseforge"
        manifest_data = json.loads(archive.read("manifest.json").decode('utf-8'))
        analysis.raw_manifest = manifest_data
        analysis.pack_name = manifest_data.get("name", "CurseForge Server")
        mc_info = manifest_data.get("minecraft", {})
        analysis.minecraft_version = mc_info.get("version", "1.20.1")
        loaders = mc_info.get("modLoaders", [])
        if loaders:
            loader_id = loaders[0].get("id", "fabric")
            if "fabric" in loader_id:
                analysis.loader = "fabric"
                analysis.loader_version = loader_id.replace("fabric-", "")
            elif "neoforge" in loader_id:
                analysis.loader = "neoforge"
                analysis.loader_version = loader_id.replace("neoforge-", "")
            elif "forge" in loader_id:
                analysis.loader = "forge"
                analysis.loader_version = loader_id.replace("forge-", "")
            elif "quilt" in loader_id:
                analysis.loader = "quilt"
                analysis.loader_version = loader_id.replace("quilt-", "")

    elif "modrinth.index.json" in namelist:
        analysis.pack_type = "modrinth"
        index_data = json.loads(archive.read("modrinth.index.json").decode('utf-8'))
        analysis.raw_manifest = index_data
        analysis.pack_name = index_data.get("name", "Modrinth Server")
        game = index_data.get("game", "minecraft")
        deps = index_data.get("dependencies", {})
        analysis.minecraft_version = deps.get("minecraft", "1.20.1")
        for l in ["fabric-loader", "neoforge", "forge", "quilt-loader"]:
            if l in deps:
                analysis.loader = l.replace("-loader", "")
                analysis.loader_version = deps[l]
                break

    else:
        analysis.pack_type = "generic_zip"
        analysis.pack_name = os.path.splitext(original_filename)[0]

    # Analyze mods inside the zip (or overrides)
    for name in namelist:
        if name.endswith(".jar") and ("mods/" in name or name.startswith("mods/")):
            filename = os.path.basename(name)
            jar_data = archive.read(name)
            mod_id, display_name, env = inspect_jar_metadata(jar_data, filename)

            if env == "client":
                analysis.client_mods_removed.append({
                    "id": mod_id,
                    "name": display_name,
                    "filename": filename,
                    "reason": "Client-only HUD, shader, rendering, or client environment"
                })
            else:
                analysis.server_mods_kept.append({
                    "id": mod_id,
                    "name": display_name,
                    "filename": filename
                })

    # Available performance mods for this loader
    perf_catalog = SERVER_PERFORMANCE_CATALOG.get(analysis.loader, SERVER_PERFORMANCE_CATALOG.get("fabric", {}))
    existing_mod_ids = {m["id"].lower() for m in analysis.server_mods_kept}

    for mod_key, mod_info in perf_catalog.items():
        is_already_present = any(mod_key in m_id for m_id in existing_mod_ids)
        analysis.recommended_performance_mods.append({
            **mod_info,
            "installed": is_already_present
        })

    return analysis, archive

def generate_server_properties(server_name: str, port: int = 25565) -> str:
    return f"""# Minecraft Server Properties - Optimized by MC Server Converter
# Generator Date: 2026
motd=\\u00a7b{server_name} \\u00a77| \\u00a7aHigh Performance
server-port={port}
max-players=20
view-distance=10
simulation-distance=8
difficulty=hard
gamemode=survival
online-mode=true
enable-command-block=true
spawn-protection=0
sync-chunk-writes=true
network-compression-threshold=256
entity-broadcast-range-percentage=80
enable-rcon=false
white-list=false
enforce-whitelist=false
prevent-proxy-connections=false
use-native-transport=true
hide-online-players=false
"""

def generate_run_scripts(loader: str, mc_version: str, memory_gb: int = 6) -> Dict[str, str]:
    aikar_flags = (
        f"-Xms{memory_gb}G -Xmx{memory_gb}G "
        "-XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 "
        "-XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch "
        "-XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1ReservePercent=20 "
        "-XX:G1HeapWastePercent=5 -XX:G1MixedGCCountTarget=4 -XX:InitiatingHeapOccupancyPercent=15 "
        "-XX:G1MixedGCLiveThresholdPercent=90 -XX:G1RSetUpdatingPauseTimePercent=5 "
        "-XX:SurvivorRatio=32 -XX:+PerfDisableSharedMem -XX:MaxTenuringThreshold=1"
    )

    sh_script = f"""#!/bin/bash
# High-performance Minecraft Server Startup
echo "Starting Minecraft {loader.upper()} {mc_version} Server with {memory_gb}G RAM..."
java {aikar_flags} -jar server.jar nogui
"""

    bat_script = f"""@echo off
REM High-performance Minecraft Server Startup for Windows
echo Starting Minecraft {loader.upper()} {mc_version} Server with {memory_gb}G RAM...
java {aikar_flags} -jar server.jar nogui
pause
"""

    dockerfile = f"""FROM itzg/minecraft-server:latest

ENV TYPE={loader.upper()}
ENV VERSION={mc_version}
ENV MEMORY={memory_gb}G
ENV EULA=true
ENV JVM_OPTS="{aikar_flags}"

COPY . /data
WORKDIR /data
EXPOSE 25565
"""

    docker_compose = f"""version: '3.8'

services:
  minecraft:
    image: itzg/minecraft-server:latest
    container_name: mc-{loader}-server
    restart: unless-stopped
    ports:
      - "25565:25565"
    environment:
      EULA: "TRUE"
      TYPE: "{loader.upper()}"
      VERSION: "{mc_version}"
      MEMORY: "{memory_gb}G"
      JVM_OPTS: "{aikar_flags}"
    volumes:
      - ./data:/data
"""

    return {
        "run.sh": sh_script,
        "run.bat": bat_script,
        "Dockerfile": dockerfile,
        "docker-compose.yml": docker_compose
    }
