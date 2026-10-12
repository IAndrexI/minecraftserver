"""
Embeddable Python Client & CLI wrapper for MC Server Converter.
Can be imported into any existing Python application or script.

Usage inside your own app:
    from mc_converter_client import convert_modpack, analyze_modpack_file

    result = convert_modpack(
        modpack_path="path/to/pack.zip",
        output_dir="./my_server",
        ram_gb=8,
        port=25565
    )
"""

import os
import io
import json
import zipfile
import argparse
from typing import Dict, Any, Optional

from converter_engine import (
    analyze_modpack,
    generate_server_properties,
    generate_run_scripts,
    query_modrinth_version
)

def analyze_modpack_file(modpack_path: str) -> Dict[str, Any]:
    """Inspects a modpack file (.zip or .mrpack) and returns stripped/kept mods."""
    with open(modpack_path, "rb") as f:
        content = f.read()
    analysis, _ = analyze_modpack(content, os.path.basename(modpack_path))
    return {
        "pack_name": analysis.pack_name,
        "minecraft_version": analysis.minecraft_version,
        "loader": analysis.loader,
        "loader_version": analysis.loader_version,
        "client_mods_removed": analysis.client_mods_removed,
        "server_mods_kept_count": len(analysis.server_mods_kept),
        "recommended_performance_mods": analysis.recommended_performance_mods
    }

def convert_modpack(
    modpack_path: str,
    output_path: str,
    ram_gb: int = 6,
    port: int = 25565,
    view_distance: int = 10,
    inject_performance_mods: bool = True
) -> Dict[str, Any]:
    """
    Converts a client modpack into a ready-to-run dedicated server bundle.
    output_path can be a folder path or a .zip file.
    """
    with open(modpack_path, "rb") as f:
        content = f.read()

    analysis, src_zip = analyze_modpack(content, os.path.basename(modpack_path))

    # Fetch recommended performance mods
    downloaded_addons = []
    if inject_performance_mods:
        import requests
        for mod in analysis.recommended_performance_mods:
            if mod.get("recommended") and not mod.get("installed"):
                file_info = query_modrinth_version(mod["project_id"], analysis.minecraft_version, analysis.loader)
                if file_info:
                    try:
                        r = requests.get(file_info["url"], timeout=10)
                        if r.status_code == 200:
                            downloaded_addons.append((file_info["filename"], r.content))
                    except Exception:
                        pass

    # Build target zip in-memory
    out_buffer = io.BytesIO()
    removed_filenames = {m["filename"] for m in analysis.client_mods_removed}

    with zipfile.ZipFile(out_buffer, 'w', zipfile.ZIP_DEFLATED) as out_zip:
        for item in src_zip.infolist():
            item_name = item.filename
            basename = os.path.basename(item_name)
            if basename in removed_filenames:
                continue
            if basename in ["options.txt", "optionsof.txt", "servers.dat"]:
                continue

            target_path = item_name
            if target_path.startswith("overrides/"):
                target_path = target_path.replace("overrides/", "", 1)
            elif target_path.startswith(".minecraft/"):
                target_path = target_path.replace(".minecraft/", "", 1)

            if target_path and not target_path.endswith("/"):
                out_zip.writestr(target_path, src_zip.read(item_name))

        for fname, fbytes in downloaded_addons:
            out_zip.writestr(f"mods/{fname}", fbytes)

        props = generate_server_properties(analysis.pack_name, port=port)
        out_zip.writestr("server.properties", props)
        out_zip.writestr("eula.txt", "eula=true\n")

        scripts = generate_run_scripts(analysis.loader, analysis.minecraft_version, memory_gb=ram_gb)
        for sname, scontent in scripts.items():
            out_zip.writestr(sname, scontent)

    # Save to output location
    out_buffer.seek(0)
    if output_path.endswith(".zip"):
        with open(output_path, "wb") as f:
            f.write(out_buffer.getvalue())
    else:
        os.makedirs(output_path, exist_ok=True)
        with zipfile.ZipFile(out_buffer) as z:
            z.extractall(output_path)

    return {
        "status": "success",
        "pack_name": analysis.pack_name,
        "minecraft_version": analysis.minecraft_version,
        "loader": analysis.loader,
        "output": output_path,
        "client_mods_stripped": len(analysis.client_mods_removed),
        "performance_mods_injected": len(downloaded_addons)
    }

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert Minecraft modpack into a dedicated server")
    parser.add_argument("input", help="Path to modpack .zip or .mrpack")
    parser.add_argument("-o", "--output", default="server_pack.zip", help="Output zip or directory")
    parser.add_argument("-r", "--ram", type=int, default=6, help="Allocated RAM in GB")
    parser.add_argument("-p", "--port", type=int, default=25565, help="Server port")
    args = parser.parse_args()

    res = convert_modpack(args.input, args.output, ram_gb=args.ram, port=args.port)
    print(json.dumps(res, indent=2))
