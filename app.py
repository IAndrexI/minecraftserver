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
    query_modrinth_version
)
from api_client import (
    search_modrinth_packs,
    search_curseforge_packs,
    get_modrinth_versions,
    get_curseforge_versions,
    DEFAULT_CF_API_KEY
)

app = FastAPI(title="Minecraft Server Modpack Converter")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

if os.path.exists(os.path.join(BASE_DIR, "static")):
    app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/search")
async def api_search_modpacks(
    q: str = Query("", min_length=0),
    provider: str = Query("all"),  # all, modrinth, curseforge
    cf_key: str = Query(None)
):
    """Searches across Modrinth and CurseForge APIs."""
    results = []
    effective_cf_key = cf_key or DEFAULT_CF_API_KEY

    if provider in ["all", "modrinth"]:
        mr_results = search_modrinth_packs(q)
        results.extend(mr_results)

    if provider in ["all", "curseforge"]:
        cf_results = search_curseforge_packs(q, api_key=effective_cf_key)
        results.extend(cf_results)

    return {"query": q, "count": len(results), "results": results}

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
    selected_mods: str = Form("[]"),
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

    # Otherwise, build the FULL server package:
    with zipfile.ZipFile(out_buffer, 'w', zipfile.ZIP_DEFLATED) as out_zip:
        removed_filenames = {m["filename"] for m in analysis.client_mods_removed}

        # Transfer server mods, configs, scripts from original pack
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

        # Add the downloaded server performance mods
        for fname, fbytes in downloaded_addons:
            out_zip.writestr(f"mods/{fname}", fbytes)

        # Generate tuned server.properties
        props_content = generate_server_properties(analysis.pack_name, port=port)
        out_zip.writestr("server.properties", props_content)

        # Accept EULA
        out_zip.writestr("eula.txt", "eula=true\n")

        # Generate run scripts & Docker files
        scripts = generate_run_scripts(analysis.loader, analysis.minecraft_version, memory_gb=ram_gb)
        for sname, scontent in scripts.items():
            out_zip.writestr(sname, scontent)

        # Detailed conversion report
        report = f"""==================================================
  MINECRAFT SERVER CONVERSION REPORT
==================================================
Modpack Name:      {analysis.pack_name}
Minecraft Version: {analysis.minecraft_version}
Loader:            {analysis.loader.upper()} ({analysis.loader_version or 'Latest'})
Allocated RAM:     {ram_gb} GB (With Aikar's G1GC Flags)

STRIPPED CLIENT-ONLY MODS ({len(analysis.client_mods_removed)}):
"""
        for cm in analysis.client_mods_removed:
            report += f" - [Removed] {cm['name']} ({cm['filename']})\n"

        report += f"\nINJECTED SERVER PERFORMANCE & ADDON MODS ({len(downloaded_addons)}):\n"
        for fname, _ in downloaded_addons:
            report += f" + [Added] {fname}\n"

        report += """
==================================================
HOW TO RUN:
- Linux / Bare Metal:   chmod +x run.sh && ./run.sh
- Windows Bare Metal:   Double-click run.bat
- Docker / Proxmox:     docker-compose up -d
==================================================
"""
        out_zip.writestr("CONVERSION_REPORT.txt", report)

    out_buffer.seek(0)
    out_filename = f"{analysis.pack_name.replace(' ', '_')}-server-pack.zip"
    return StreamingResponse(
        out_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={out_filename}"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)
