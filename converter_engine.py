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
        if known_norm in norm_id:
            environment = "client"
            break

    return mod_id, name, environment

KNOWN_SERVER_ONLY_MODS = {
    "ledger", "spark", "chunky", "chunkyborder", "chunky-border",
    "servux", "luckperms", "audioplayer", "simple-voice-chat-server",
    "bungeeguard", "velocity", "floodgate", "geyser", "geyser-fabric",
    "geyser-spigot", "packetfixer", "vmp", "krypton", "carpet",
    "essential-commands", "server-tap", "bluemap", "dynmap"
}

def classify_mod_side(filename: str, jar_data: Optional[bytes] = None) -> str:
    """
    Classifies a mod as 'client', 'server', or 'both'.
    """
    norm = sanitize_id(os.path.splitext(filename)[0]).lower().replace("-", "").replace("_", "")
    
    # 1. Check known server-only mods
    for s in KNOWN_SERVER_ONLY_MODS:
        s_norm = s.replace("-", "").replace("_", "")
        if s_norm in norm:
            return "server"

    # 2. Check known client-only mods
    for c in KNOWN_CLIENT_MODS:
        c_norm = c.replace("-", "").replace("_", "")
        if c_norm in norm:
            return "client"

    # 3. If jar_data is provided, inspect internal metadata
    if jar_data:
        _, _, env = inspect_jar_metadata(jar_data, filename)
        if env in ["client", "server"]:
            return env

    return "both"

def resolve_loader_version(loader: str, mc_version: str) -> str:
    """
    Resolves the recommended/latest modloader version for a given Minecraft version
    so that CurseForge manifest.json and Modrinth modrinth.index.json have exact valid loader IDs.
    """
    loader_norm = loader.lower().strip()
    try:
        if loader_norm == "fabric":
            res = requests.get(f"https://meta.fabricmc.net/v2/versions/loader/{mc_version}", timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data and isinstance(data, list):
                    return data[0].get("loader", {}).get("version", "0.16.10")
            return "0.16.10"

        elif loader_norm == "quilt":
            res = requests.get(f"https://meta.quiltmc.org/v3/versions/loader/{mc_version}", timeout=5)
            if res.status_code == 200:
                data = res.json()
                if data and isinstance(data, list):
                    return data[0].get("loader", {}).get("version", "0.26.4")
            return "0.26.4"

        elif loader_norm == "forge":
            res = requests.get("https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json", timeout=5)
            if res.status_code == 200:
                promos = res.json().get("promos", {})
                ver = promos.get(f"{mc_version}-recommended") or promos.get(f"{mc_version}-latest")
                if ver:
                    return ver
            # Common fallbacks by MC version
            forge_fallbacks = {
                "1.20.1": "47.3.0",
                "1.19.2": "43.4.0",
                "1.18.2": "40.2.21",
                "1.16.5": "36.2.42",
                "1.12.2": "14.23.5.2860"
            }
            return forge_fallbacks.get(mc_version, "47.3.0")

        elif loader_norm == "neoforge":
            res = requests.get("https://maven.neoforged.net/api/maven/versions/releases/net/neoforged/neoforge", timeout=5)
            if res.status_code == 200:
                versions = res.json().get("versions", [])
                # NeoForge versions match MC minor.patch (e.g. MC 1.21.1 -> 21.1.x, MC 1.20.4 -> 20.4.x)
                parts = mc_version.split(".")
                if len(parts) >= 2:
                    prefix = f"{parts[1]}.{parts[2]}." if len(parts) >= 3 else f"{parts[1]}.0."
                    matching = [v for v in versions if v.startswith(prefix) and "beta" not in v]
                    if matching:
                        return matching[-1]
            return "21.1.77" if mc_version.startswith("1.21") else "20.4.237"
    except Exception as e:
        logger.warning(f"Loader version lookup failed for {loader} {mc_version}: {e}")

    defaults = {"fabric": "0.16.10", "quilt": "0.26.4", "forge": "47.3.0", "neoforge": "21.1.77"}
    return defaults.get(loader_norm, "0.16.10")


def query_modrinth_version(project_slug: str, mc_version: str, loader: str) -> Optional[Dict[str, Any]]:
    """Fetches compatible file download and hash metadata for a mod from Modrinth API."""
    try:
        url = f"{MODRINTH_API_BASE}/project/{project_slug}/version"
        params = {
            "game_versions": json.dumps([mc_version]),
            "loaders": json.dumps([loader.lower()])
        }
        res = requests.get(url, params=params, timeout=6)
        if res.status_code == 200:
            versions = res.json()
            if versions:
                v = versions[0]
                files = v.get("files", [])
                primary_file = next((f for f in files if f.get("primary")), files[0] if files else None)
                if primary_file:
                    return {
                        "provider": "modrinth",
                        "project_id": v.get("project_id", project_slug),
                        "version_id": v.get("id"),
                        "filename": primary_file["filename"],
                        "url": primary_file["url"],
                        "hashes": primary_file.get("hashes", {}),
                        "size": primary_file.get("size", 0),
                        "version_number": v.get("version_number", "1.0.0")
                    }
    except Exception as e:
        logger.warning(f"Modrinth lookup failed for {project_slug}: {e}")
    return None


def query_curseforge_mod_file(mod_id_or_slug: str, mc_version: str, loader: str, api_key: str) -> Optional[Dict[str, Any]]:
    """Fetches compatible CurseForge mod file metadata (projectID, fileID, downloadUrl, hashes)."""
    if not api_key:
        return None
    headers = {"x-api-key": api_key, "Accept": "application/json"}
    loader_type_map = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
    loader_type = loader_type_map.get(loader.lower(), 4)

    try:
        mod_id = str(mod_id_or_slug).strip()
        # If slug was passed instead of numeric ID, search by slug first
        if not mod_id.isdigit():
            s_res = requests.get(
                "https://api.curseforge.com/v1/mods/search",
                headers=headers,
                params={"gameId": 432, "classId": 6, "slug": mod_id},
                timeout=6
            )
            if s_res.status_code == 200:
                s_data = s_res.json().get("data", [])
                if s_data:
                    mod_id = str(s_data[0]["id"])
                else:
                    return None
            else:
                return None

        files_url = f"https://api.curseforge.com/v1/mods/{mod_id}/files"
        params = {
            "gameVersion": mc_version,
            "modLoaderType": loader_type,
            "pageSize": 5
        }
        res = requests.get(files_url, headers=headers, params=params, timeout=6)
        if res.status_code == 200:
            files = res.json().get("data", [])
            if files:
                f = files[0]
                file_id = f.get("id")
                filename = f.get("fileName")
                dl_url = f.get("downloadUrl")
                if not dl_url and file_id and filename:
                    # Standard CurseForge edge CDN fallback when downloadUrl is null
                    fid_str = str(file_id)
                    dl_url = f"https://edge.forgecdn.net/files/{fid_str[:4]}/{int(fid_str[4:])}/{filename}"
                hashes = {}
                for h in f.get("hashes", []):
                    if h.get("algo") == 1:
                        hashes["sha1"] = h.get("value")
                    elif h.get("algo") == 2:
                        hashes["md5"] = h.get("value")
                return {
                    "provider": "curseforge",
                    "project_id": int(mod_id),
                    "file_id": int(file_id),
                    "filename": filename,
                    "url": dl_url,
                    "hashes": hashes,
                    "size": f.get("fileLength", 0),
                    "version_number": f.get("displayName", filename)
                }
    except Exception as e:
        logger.warning(f"CurseForge lookup failed for {mod_id_or_slug}: {e}")
    return None


def build_curseforge_pack_bytes(
    pack_name: str,
    mc_version: str,
    loader: str,
    loader_version: str,
    cf_manifest_files: List[Dict[str, Any]],
    modlist_entries: List[Dict[str, str]],
    override_mods: List[Tuple[str, bytes]],
    extra_overrides: Optional[Dict[str, bytes]] = None
) -> bytes:
    """
    Creates a 100% CurseForge-compliant modpack .zip containing:
      - manifest.json
      - modlist.html
      - overrides/ (with any non-CF mods or config files)
    """
    buf = io.BytesIO()
    loader_norm = loader.lower()
    cf_loader_id = f"{loader_norm}-{loader_version}"

    manifest = {
        "minecraft": {
            "version": mc_version,
            "modLoaders": [
                {
                    "id": cf_loader_id,
                    "primary": True
                }
            ]
        },
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": pack_name,
        "version": "1.0.0",
        "author": "Protutech",
        "files": cf_manifest_files,
        "overrides": "overrides"
    }

    modlist_lines = ["<ul>"]
    for item in modlist_entries:
        title = item.get("title") or item.get("filename") or "Mod"
        author = item.get("author") or "Author"
        page_url = item.get("page_url") or "#"
        modlist_lines.append(f'<li><a href="{page_url}">{title} (by {author})</a></li>')
    modlist_lines.append("</ul>")
    modlist_html = "\n".join(modlist_lines)

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("modlist.html", modlist_html)
        for fname, fbytes in override_mods:
            zf.writestr(f"overrides/mods/{fname}", fbytes)
        if extra_overrides:
            for rel_path, data in extra_overrides.items():
                zf.writestr(f"overrides/{rel_path}", data)

    buf.seek(0)
    return buf.read()


def build_modrinth_mrpack_bytes(
    pack_name: str,
    mc_version: str,
    loader: str,
    loader_version: str,
    mr_index_files: List[Dict[str, Any]],
    override_mods: List[Tuple[str, bytes]],
    extra_overrides: Optional[Dict[str, bytes]] = None
) -> bytes:
    """
    Creates a 100% Modrinth-compliant .mrpack archive containing:
      - modrinth.index.json
      - overrides/ (with any non-Modrinth CDN mods or config files)
    """
    buf = io.BytesIO()
    loader_norm = loader.lower()
    dep_key_map = {
        "fabric": "fabric-loader",
        "quilt": "quilt-loader",
        "forge": "forge",
        "neoforge": "neoforge"
    }
    loader_dep_key = dep_key_map.get(loader_norm, "fabric-loader")

    index_data = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "1.0.0",
        "name": pack_name,
        "summary": f"{pack_name} for Minecraft {mc_version} ({loader.upper()})",
        "files": mr_index_files,
        "dependencies": {
            "minecraft": mc_version,
            loader_dep_key: loader_version
        }
    }

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("modrinth.index.json", json.dumps(index_data, indent=2))
        for fname, fbytes in override_mods:
            zf.writestr(f"overrides/mods/{fname}", fbytes)
        if extra_overrides:
            for rel_path, data in extra_overrides.items():
                zf.writestr(f"overrides/{rel_path}", data)

    buf.seek(0)
    return buf.read()


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

    # Available performance and utility mods for this loader
    from converter_catalog import EXPANDED_SERVER_MODS_CATALOG
    perf_catalog = EXPANDED_SERVER_MODS_CATALOG.get(analysis.loader, EXPANDED_SERVER_MODS_CATALOG.get("fabric", []))
    existing_mod_ids = {m["id"].lower() for m in analysis.server_mods_kept}

    for mod_info in perf_catalog:
        mod_key = mod_info["mod_id"].lower()
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
