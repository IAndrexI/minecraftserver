"""
FastAPI web server handling modpack uploads, online API search (CurseForge + Modrinth),
side analysis, and server bundle generation.
"""

import os
import io
import json
import zipfile
import requests
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from converter_engine import (
    analyze_modpack,
    generate_server_properties,
    generate_run_scripts,
    query_modrinth_version,
    classify_mod_side
)
from api_client import (
    search_modrinth_packs,
    search_curseforge_packs,
    get_modrinth_versions,
    get_curseforge_versions,
    get_all_minecraft_versions,
    search_version_mods,
    DEFAULT_CF_API_KEY
)

app = FastAPI(title="Minecraft Server Modpack Converter")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

if os.path.exists(os.path.join(BASE_DIR, "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

@app.get("/api/minecraft-versions")
async def api_get_minecraft_versions():
    """Returns all release versions of Minecraft."""
    versions = get_all_minecraft_versions()
    return {"versions": versions}

@app.get("/api/search-mods")
async def api_search_version_mods(
    q: str = Query("", min_length=0),
    mc_version: str = Query("1.20.1"),
    loader: str = Query("fabric"),
    provider: str = Query("all"),
    sort: str = Query("downloads"),
    category: str = Query(""),
    limit: int = Query(100),
    offset: int = Query(0),
    cf_key: str = Query(None)
):
    """Searches mods strictly compatible with the selected MC version and loader with sorting & filters."""
    mods = search_version_mods(
        query=q,
        mc_version=mc_version,
        loader=loader,
        provider=provider,
        sort=sort,
        category=category,
        api_key=cf_key or DEFAULT_CF_API_KEY,
        limit=limit,
        offset=offset
    )
    return {
        "mc_version": mc_version,
        "loader": loader,
        "sort": sort,
        "category": category,
        "count": len(mods),
        "offset": offset,
        "mods": mods
    }

@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

from compatibility_tester import test_mod_compatibility
from converter_catalog import EXPANDED_SERVER_MODS_CATALOG

@app.post("/api/test-compatibility")
async def api_test_compatibility(
    mods_json: str = Form("[]"),
    loader: str = Form("fabric"),
    mc_version: str = Form("1.20.1")
):
    """Simulates a server boot test and evaluates mutual mod compatibility & conflicts."""
    import json
    try:
        mods_list = json.loads(mods_json)
    except Exception:
        mods_list = []

    report = test_mod_compatibility(mods_list, loader=loader, mc_version=mc_version)
    return {
        "passed": report.passed,
        "simulated_load_success": report.simulated_load_success,
        "summary": report.summary,
        "conflicts": report.conflicts_found,
        "warnings": report.warnings,
        "errors": report.errors,
        "client_only_detected": report.client_only_detected
    }

@app.get("/api/catalog-mods")
async def api_get_catalog_mods(loader: str = "fabric"):
    """Returns the full catalog of performance, utility, and administration mods."""
    mods = EXPANDED_SERVER_MODS_CATALOG.get(loader.lower(), EXPANDED_SERVER_MODS_CATALOG.get("fabric", []))
    return {"loader": loader, "mods": mods}

@app.post("/api/create-custom-pack")
async def api_create_custom_pack(
    pack_name: str = Form("Custom Server Pack"),
    loader: str = Form("fabric"),
    mc_version: str = Form("1.20.1"),
    selected_mods_json: str = Form("[]"),
    export_target: str = Form("dual"),
    ram_gb: int = Form(6),
    port: int = Form(25565)
):
    """
    Builds a custom modpack from selected mods from scratch.
    Supports exporting:
      - 'dual': separate 'client/' and 'server/' folders inside one unified ZIP archive.
      - 'server': dedicated server package ready for host / Docker.
      - 'client': client modpack package ready for launcher / players.
    """
    import json
    import requests
    slugs = json.loads(selected_mods_json)
    out_buffer = io.BytesIO()

    # Pre-test compatibility
    test_mods = [{"project_id": s} for s in slugs]
    report = test_mod_compatibility(test_mods, loader=loader, mc_version=mc_version)

    downloaded = []  # List of tuples: (filename, bytes, side)
    for slug in slugs:
        file_info = query_modrinth_version(slug, mc_version, loader)
        if file_info:
            try:
                r = requests.get(file_info["url"], timeout=10)
                if r.status_code == 200:
                    side = classify_mod_side(file_info["filename"], r.content)
                    downloaded.append((file_info["filename"], r.content, side))
            except Exception:
                pass

    server_mods = [d for d in downloaded if d[2] in ["server", "both"]]
    client_mods = [d for d in downloaded if d[2] in ["client", "both"]]

    with zipfile.ZipFile(out_buffer, 'w', zipfile.ZIP_DEFLATED) as out_zip:
        if export_target == "dual":
            # 1. Client Folder
            for fname, fbytes, _ in client_mods:
                out_zip.writestr(f"client/mods/{fname}", fbytes)
            
            client_readme = f"""==================================================
  {pack_name} - CLIENT MODPACK (MC {mc_version} {loader.upper()})
==================================================
This folder is for PLAYERS to install in their launcher.

HOW TO INSTALL:
1. Open Prism Launcher / Modrinth App / CurseForge / ATLauncher or official Minecraft.
2. Create or open an instance for Minecraft {mc_version} ({loader.upper()}).
3. Copy all files from 'client/mods/' into your instance's 'mods/' directory.
4. Launch and connect to your dedicated server!

Total Client Mods: {len(client_mods)}
"""
            out_zip.writestr("client/README.txt", client_readme)

            # 2. Server Folder
            for fname, fbytes, _ in server_mods:
                out_zip.writestr(f"server/mods/{fname}", fbytes)

            props = generate_server_properties(pack_name, port=port)
            out_zip.writestr("server/server.properties", props)
            out_zip.writestr("server/eula.txt", "eula=true\n")

            scripts = generate_run_scripts(loader, mc_version, memory_gb=ram_gb)
            for sname, scontent in scripts.items():
                out_zip.writestr(f"server/{sname}", scontent)

            server_readme = f"""==================================================
  {pack_name} - DEDICATED SERVER (MC {mc_version} {loader.upper()})
==================================================
This folder is for HOSTING the dedicated multiplayer server.

HOW TO RUN:
- Linux / Bare Metal:   chmod +x run.sh && ./run.sh
- Windows Bare Metal:   Double-click run.bat
- Docker / Proxmox:     docker-compose up -d

Allocated RAM:     {ram_gb} GB (Aikar G1GC Flags)
Total Server Mods: {len(server_mods)}
"""
            out_zip.writestr("server/README.txt", server_readme)

            # 3. Root README
            root_readme = f"""# {pack_name}

Minecraft: {mc_version} | Loader: {loader.upper()} | Generated by MC Server Converter

This archive contains separated distributions for players and the server host:

📂 **`client/`** (For Players)
Contains all gameplay mods and client enhancements. Copy `client/mods` into your Minecraft launcher instance.

📂 **`server/`** (For Server Host)
Contains the stripped server mods, `server.properties`, `eula.txt`, `run.sh` / `run.bat`, and Docker configuration. Client-only crash mods have been removed.

---
Compatibility Report:
{report.summary}
"""
            out_zip.writestr("README.md", root_readme)
            filename = f"{pack_name.replace(' ', '_')}-dual-pack.zip"

        elif export_target == "client":
            # Client only
            for fname, fbytes, _ in client_mods:
                out_zip.writestr(f"mods/{fname}", fbytes)
            
            client_readme = f"""==================================================
  {pack_name} - CLIENT MODPACK (MC {mc_version} {loader.upper()})
==================================================
Install this into your Prism Launcher, CurseForge, or Minecraft client instance.
Copy 'mods/' into your Minecraft directory.
Total Mods: {len(client_mods)}
"""
            out_zip.writestr("README.txt", client_readme)
            filename = f"{pack_name.replace(' ', '_')}-client.zip"

        else:  # server only
            for fname, fbytes, _ in server_mods:
                out_zip.writestr(f"mods/{fname}", fbytes)

            props = generate_server_properties(pack_name, port=port)
            out_zip.writestr("server.properties", props)
            out_zip.writestr("eula.txt", "eula=true\n")

            scripts = generate_run_scripts(loader, mc_version, memory_gb=ram_gb)
            for sname, scontent in scripts.items():
                out_zip.writestr(sname, scontent)

            summary_txt = f"""CUSTOM SERVER MODPACK CREATED BY MC SERVER CONVERTER
Pack Name:         {pack_name}
Minecraft Version: {mc_version}
Loader:            {loader.upper()}
Allocated RAM:     {ram_gb} GB

COMPATIBILITY STATUS:
{report.summary}

INCLUDED SERVER MODS ({len(server_mods)}):
"""
            for fname, _, _ in server_mods:
                summary_txt += f" + {fname}\n"

            out_zip.writestr("PACK_INFO.txt", summary_txt)
            filename = f"{pack_name.replace(' ', '_')}-server.zip"

    out_buffer.seek(0)
    return StreamingResponse(
        out_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
@app.post("/api/export-to-discopanel")
async def api_export_to_discopanel(
    pack_name: str = Form("Converted Server"),
    download_url: str = Form(None),
    server_dir: str = Form("/opt/discopanel/data/servers")
):
    """Auto-imports converted server files directly to DiscoPanel data directory if accessible."""
    import uuid
    import shutil

    if not os.path.exists(server_dir):
        raise HTTPException(status_code=400, detail=f"DiscoPanel directory not found at {server_dir}. Ensure DiscoPanel is installed on the host or mount its directory.")

    server_uuid = str(uuid.uuid4())
    target_path = os.path.join(server_dir, server_uuid)
    os.makedirs(target_path, exist_ok=True)

    if download_url:
        r = requests.get(download_url, timeout=60)
        if r.status_code == 200:
            with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                z.extractall(target_path)
            return {"status": "success", "server_id": server_uuid, "path": target_path}

    return {"status": "error", "detail": "Missing modpack content"}

@app.get("/api/search")
async def api_search_modpacks(
    q: str = Query("", min_length=0),
    provider: str = Query("all"),  # all, modrinth, curseforge
    sort: str = Query("downloads"),
    cf_key: str = Query(None)
):
    """Searches across Modrinth and CurseForge APIs with sorting."""
    results = []
    effective_cf_key = cf_key or DEFAULT_CF_API_KEY

    if provider in ["all", "modrinth"]:
        mr_results = search_modrinth_packs(q, sort=sort)
        results.extend(mr_results)

    if provider in ["all", "curseforge"]:
        cf_results = search_curseforge_packs(q, sort=sort, api_key=effective_cf_key)
        results.extend(cf_results)

    if provider == "all":
        if sort.lower() == "name":
            results.sort(key=lambda x: (x.get("title") or "").lower())
        elif sort.lower() in ["downloads", "popularity"]:
            results.sort(key=lambda x: x.get("downloads", 0), reverse=True)

    return {"query": q, "sort": sort, "count": len(results), "results": results}

@app.get("/api/versions")
async def api_get_pack_versions(
    provider: str = Query(...),
    project_id: str = Query(...),
    cf_key: str = Query(None)
):
    """Retrieves versions/files for a selected modpack."""
    if provider == "modrinth":
        return {"versions": get_modrinth_versions(project_id)}
    elif provider == "curseforge":
        return {"versions": get_curseforge_versions(project_id, api_key=cf_key or DEFAULT_CF_API_KEY)}
    return {"versions": []}

@app.post("/api/analyze-remote")
async def api_analyze_remote_modpack(
    download_url: str = Form(...),
    filename: str = Form("modpack.zip")
):
    """Downloads a modpack directly from CurseForge/Modrinth URL and analyzes it."""
    try:
        r = requests.get(download_url, timeout=30)
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Failed to download modpack (HTTP {r.status_code})")
        content = r.content
        analysis, _ = analyze_modpack(content, filename)
        return {
            "pack_name": analysis.pack_name,
            "minecraft_version": analysis.minecraft_version,
            "loader": analysis.loader,
            "loader_version": analysis.loader_version,
            "pack_type": analysis.pack_type,
            "client_mods_removed": analysis.client_mods_removed,
            "server_mods_kept_count": len(analysis.server_mods_kept),
            "recommended_performance_mods": analysis.recommended_performance_mods,
            "download_url": download_url
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing remote modpack: {str(e)}")

@app.post("/api/analyze")
async def api_analyze_modpack(file: UploadFile = File(...)):
    content = await file.read()
    if not (file.filename.endswith(".zip") or file.filename.endswith(".mrpack")):
        raise HTTPException(status_code=400, detail="File must be a .zip or .mrpack archive")

    analysis, _ = analyze_modpack(content, file.filename)
    return {
        "pack_name": analysis.pack_name,
        "minecraft_version": analysis.minecraft_version,
        "loader": analysis.loader,
        "loader_version": analysis.loader_version,
        "pack_type": analysis.pack_type,
        "client_mods_removed": analysis.client_mods_removed,
        "server_mods_kept_count": len(analysis.server_mods_kept),
        "recommended_performance_mods": analysis.recommended_performance_mods
    }

@app.post("/api/convert")
async def api_convert_modpack(
    file: UploadFile = File(None),
    download_url: str = Form(None),
    world_file: UploadFile = File(None),
    selected_mods: str = Form("[]"),
    export_target: str = Form("server"),  # "dual", "server", "client"
    ram_gb: int = Form(6),
    port: int = Form(25565),
    view_distance: int = Form(10),
    simulation_distance: int = Form(8),
    additional_only: bool = Form(False)
):
    if file:
        content = await file.read()
        filename = file.filename
    elif download_url:
        r = requests.get(download_url, timeout=45)
        if r.status_code != 200:
            raise HTTPException(status_code=400, detail="Failed to fetch remote modpack file")
        content = r.content
        filename = "remote_modpack.zip"
    else:
        raise HTTPException(status_code=400, detail="No file or download URL provided")

    # Read uploaded world save if provided
    world_bytes = None
    if world_file and world_file.filename:
        world_bytes = await world_file.read()

    analysis, src_zip = analyze_modpack(content, filename)
    mod_slugs_to_add = json.loads(selected_mods)

    out_buffer = io.BytesIO()

    # 1. Download selected performance / add-on mods from Modrinth
    downloaded_addons = []
    for slug in mod_slugs_to_add:
        mod_file = query_modrinth_version(slug, analysis.minecraft_version, analysis.loader)
        if mod_file:
            try:
                r = requests.get(mod_file["url"], timeout=10)
                if r.status_code == 200:
                    downloaded_addons.append((mod_file["filename"], r.content))
            except Exception:
                pass

    # If the user only requested the Add-ons ZIP:
    if additional_only:
        with zipfile.ZipFile(out_buffer, 'w', zipfile.ZIP_DEFLATED) as addon_zip:
            for fname, fbytes in downloaded_addons:
                addon_zip.writestr(f"mods/{fname}", fbytes)
            
            readme = (
                f"Additional Server Mods for {analysis.pack_name}\n"
                f"Minecraft: {analysis.minecraft_version} | Loader: {analysis.loader}\n\n"
                "Drop these .jar files into your server's 'mods/' directory.\n"
            )
            addon_zip.writestr("README.txt", readme)

        out_buffer.seek(0)
        out_filename = f"{analysis.pack_name.replace(' ', '_')}-server-addons.zip"
        return StreamingResponse(
            out_buffer,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={out_filename}"}
        )

    # Build the package according to export_target ('dual', 'client', or 'server'):
    with zipfile.ZipFile(out_buffer, 'w', zipfile.ZIP_DEFLATED) as out_zip:
        removed_filenames = {m["filename"] for m in analysis.client_mods_removed}

        # Helper to normalize source paths
        def normalize_path(raw_name: str) -> str:
            path = raw_name
            if path.startswith("overrides/"):
                path = path.replace("overrides/", "", 1)
            elif path.startswith(".minecraft/"):
                path = path.replace(".minecraft/", "", 1)
            return path

        props_content = generate_server_properties(analysis.pack_name, port=port)
        scripts = generate_run_scripts(analysis.loader, analysis.minecraft_version, memory_gb=ram_gb)

        conversion_report = f"""==================================================
  MINECRAFT SERVER CONVERSION REPORT
==================================================
Modpack Name:      {analysis.pack_name}
Minecraft Version: {analysis.minecraft_version}
Loader:            {analysis.loader.upper()} ({analysis.loader_version or 'Latest'})
Allocated RAM:     {ram_gb} GB (With Aikar's G1GC Flags)

STRIPPED CLIENT-ONLY MODS ({len(analysis.client_mods_removed)}):
"""
        for cm in analysis.client_mods_removed:
            conversion_report += f" - [Removed] {cm['name']} ({cm['filename']})\n"

        conversion_report += f"\nINJECTED SERVER PERFORMANCE & ADDON MODS ({len(downloaded_addons)}):\n"
        for fname, _ in downloaded_addons:
            conversion_report += f" + [Added] {fname}\n"

        conversion_report += """
==================================================
HOW TO RUN DEDICATED SERVER:
- Linux / Bare Metal:   chmod +x run.sh && ./run.sh
- Windows Bare Metal:   Double-click run.bat
- Docker / Proxmox:     docker-compose up -d
==================================================
"""

        # Function to write world to a target prefix
        def write_world(prefix: str):
            if not world_bytes:
                return
            try:
                with zipfile.ZipFile(io.BytesIO(world_bytes)) as wz:
                    root_prefix = ""
                    for member in wz.namelist():
                        if "level.dat" in member:
                            root_prefix = member.split("level.dat")[0]
                            break
                    for witem in wz.infolist():
                        if witem.is_dir():
                            continue
                        rel_path = witem.filename
                        if root_prefix and rel_path.startswith(root_prefix):
                            rel_path = rel_path[len(root_prefix):]
                        if rel_path:
                            out_zip.writestr(f"{prefix}world/{rel_path}", wz.read(witem.filename))
            except Exception:
                pass

        if export_target == "dual":
            # --- 1. Client Folder ---
            for item in src_zip.infolist():
                if item.is_dir():
                    continue
                target_path = normalize_path(item.filename)
                if target_path:
                    out_zip.writestr(f"client/{target_path}", src_zip.read(item.filename))

            client_readme = f"""{analysis.pack_name} - Client Modpack
Minecraft: {analysis.minecraft_version} | Loader: {analysis.loader.upper()}

This folder is for PLAYERS to install in their launcher.
Copy 'client/mods' (and configs/resourcepacks) into your Minecraft client directory.
"""
            out_zip.writestr("client/README.txt", client_readme)

            # --- 2. Server Folder ---
            for item in src_zip.infolist():
                if item.is_dir():
                    continue
                basename = os.path.basename(item.filename)
                if basename in removed_filenames or basename in ["options.txt", "optionsof.txt", "servers.dat"]:
                    continue
                target_path = normalize_path(item.filename)
                if target_path:
                    out_zip.writestr(f"server/{target_path}", src_zip.read(item.filename))

            for fname, fbytes in downloaded_addons:
                out_zip.writestr(f"server/mods/{fname}", fbytes)

            write_world("server/")
            out_zip.writestr("server/server.properties", props_content)
            out_zip.writestr("server/eula.txt", "eula=true\n")
            for sname, scontent in scripts.items():
                out_zip.writestr(f"server/{sname}", scontent)
            out_zip.writestr("server/CONVERSION_REPORT.txt", conversion_report)

            # --- 3. Root README ---
            root_readme = f"""# {analysis.pack_name} (Dual Distribution)

Minecraft: {analysis.minecraft_version} | Loader: {analysis.loader.upper()}

This archive contains separated distributions for both players and the dedicated server:

📁 **`client/`** (For Players)
Contains all gameplay mods, shaders, HUDs, and client configurations. Give this to players to put in their launcher.

📁 **`server/`** (For Dedicated Server)
Contains stripped server mods with client-crashing mods removed, injected performance mods, `server.properties`, `eula.txt`, `run.sh` / `run.bat`, and Docker files.
"""
            out_zip.writestr("README.md", root_readme)
            out_filename = f"{analysis.pack_name.replace(' ', '_')}-dual-pack.zip"

        elif export_target == "client":
            # Client Only
            for item in src_zip.infolist():
                if item.is_dir():
                    continue
                target_path = normalize_path(item.filename)
                if target_path:
                    out_zip.writestr(target_path, src_zip.read(item.filename))

            client_readme = f"""{analysis.pack_name} - Client Modpack
Minecraft: {analysis.minecraft_version} | Loader: {analysis.loader.upper()}
Copy this directory into your Minecraft launcher instance.
"""
            out_zip.writestr("README.txt", client_readme)
            out_filename = f"{analysis.pack_name.replace(' ', '_')}-client-pack.zip"

        else:
            # Server Only (Default)
            for item in src_zip.infolist():
                if item.is_dir():
                    continue
                basename = os.path.basename(item.filename)
                if basename in removed_filenames or basename in ["options.txt", "optionsof.txt", "servers.dat"]:
                    continue
                target_path = normalize_path(item.filename)
                if target_path:
                    out_zip.writestr(target_path, src_zip.read(item.filename))

            for fname, fbytes in downloaded_addons:
                out_zip.writestr(f"mods/{fname}", fbytes)

            write_world("")
            out_zip.writestr("server.properties", props_content)
            out_zip.writestr("eula.txt", "eula=true\n")
            for sname, scontent in scripts.items():
                out_zip.writestr(sname, scontent)
            out_zip.writestr("CONVERSION_REPORT.txt", conversion_report)
            out_filename = f"{analysis.pack_name.replace(' ', '_')}-server-pack.zip"

    out_buffer.seek(0)
    return StreamingResponse(
        out_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={out_filename}"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
