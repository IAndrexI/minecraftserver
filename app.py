"""
FastAPI web server handling modpack uploads, online API search (CurseForge + Modrinth),
side analysis, and server bundle generation.
"""

import os
import io
import json
import uuid
import tempfile
import zipfile
import requests
import hashlib
from fastapi import FastAPI, UploadFile, File, Form, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from converter_engine import (
    analyze_modpack,
    generate_server_properties,
    generate_run_scripts,
    resolve_loader_version,
    query_modrinth_version,
    query_curseforge_mod_file,
    build_curseforge_pack_bytes,
    build_modrinth_mrpack_bytes,
    classify_mod_side,
    get_java_runtime_for_mc,
    inspect_world_save,
    normalize_world_save_zip
)
from discopanel_deployer import (
    test_discopanel_connection,
    deploy_to_discopanel_host
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
DISCO_STAGE_DIR = os.path.join(tempfile.gettempdir(), "discopanel_staged")
os.makedirs(DISCO_STAGE_DIR, exist_ok=True)
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
    port: int = Form(25565),
    stage_for_discopanel: bool = Form(False),
    cf_key: str = Form(None)
):
    """
    Builds a custom modpack from selected mods from scratch.
    Supports exporting:
      - 'curseforge': CurseForge-ready .zip (manifest.json + modlist.html + overrides/)
      - 'modrinth': Modrinth-ready .mrpack (modrinth.index.json + overrides/)
      - 'dual': Unified archive containing CurseForge .zip, Modrinth .mrpack, client/ folder, and server/ folder
      - 'server': Dedicated server package ready for host / Docker / CurseForge Server Pack upload
      - 'client': Client modpack package ready for launcher / players
    """
    raw_items = json.loads(selected_mods_json)
    effective_cf_key = cf_key or DEFAULT_CF_API_KEY
    loader_version = resolve_loader_version(loader, mc_version)

    # Normalize selected items (can be string IDs/slugs or dicts with metadata)
    normalized_mods = []
    for item in raw_items:
        if isinstance(item, dict):
            normalized_mods.append({
                "id": str(item.get("id") or item.get("slug") or ""),
                "slug": str(item.get("slug") or item.get("id") or ""),
                "provider": item.get("provider") or ("curseforge" if str(item.get("id", "")).isdigit() else "modrinth"),
                "title": item.get("title") or item.get("slug") or "Mod",
                "author": item.get("author") or "Author",
                "page_url": item.get("page_url") or ""
            })
        else:
            s_val = str(item)
            normalized_mods.append({
                "id": s_val,
                "slug": s_val,
                "provider": "curseforge" if s_val.isdigit() else "modrinth",
                "title": s_val,
                "author": "Author",
                "page_url": ""
            })

    # Pre-test compatibility
    test_mods = [{"project_id": m["slug"] or m["id"]} for m in normalized_mods]
    report = test_mod_compatibility(test_mods, loader=loader, mc_version=mc_version)

    downloaded = []          # List of dicts with filename, bytes, side, mr_info, cf_info, meta
    cf_manifest_files = []   # [{"projectID": int, "fileID": int, "required": True}]
    cf_modlist_entries = []  # [{"title": ..., "author": ..., "page_url": ...}]
    cf_override_mods = []    # [(filename, bytes)] for mods not on CurseForge
    mr_index_files = []      # Modrinth modrinth.index.json files array
    mr_override_mods = []    # [(filename, bytes)] for mods not on Modrinth CDN

    seen_cf_projects = set()
    seen_filenames = set()

    for m in normalized_mods:
        mr_info = None
        cf_info = None

        # 1. Try primary provider first, then cross-resolve so both CF & MR manifests are populated
        if m["provider"] == "curseforge":
            cf_info = query_curseforge_mod_file(m["id"], mc_version, loader, effective_cf_key)
            if m["slug"] and not m["slug"].isdigit():
                mr_info = query_modrinth_version(m["slug"], mc_version, loader)
        else:
            mr_info = query_modrinth_version(m["id"] or m["slug"], mc_version, loader)
            if not mr_info and m["slug"]:
                mr_info = query_modrinth_version(m["slug"], mc_version, loader)
            if m["slug"]:
                cf_info = query_curseforge_mod_file(m["slug"], mc_version, loader, effective_cf_key)

        # Download JAR bytes from whichever provider resolved
        dl_url = (mr_info and mr_info.get("url")) or (cf_info and cf_info.get("url"))
        fname = (mr_info and mr_info.get("filename")) or (cf_info and cf_info.get("filename"))
        if not dl_url or not fname or fname in seen_filenames:
            continue

        jar_bytes = None
        try:
            r = requests.get(dl_url, timeout=12)
            if r.status_code == 200:
                jar_bytes = r.content
        except Exception:
            pass

        if not jar_bytes:
            continue

        seen_filenames.add(fname)
        side = classify_mod_side(fname, jar_bytes)

        downloaded.append({
            "filename": fname,
            "bytes": jar_bytes,
            "side": side,
            "meta": m
        })

        # Populate CurseForge manifest entry or fallback to CF overrides/mods/
        if cf_info and cf_info.get("project_id") and cf_info.get("file_id"):
            pid = int(cf_info["project_id"])
            fid = int(cf_info["file_id"])
            if pid not in seen_cf_projects:
                seen_cf_projects.add(pid)
                cf_manifest_files.append({
                    "projectID": pid,
                    "fileID": fid,
                    "required": True
                })
                cf_modlist_entries.append({
                    "title": m["title"],
                    "author": m["author"],
                    "page_url": m["page_url"] or f"https://www.curseforge.com/minecraft/mc-mods/{m['slug']}"
                })
        else:
            if side in ["client", "both"]:
                cf_override_mods.append((fname, jar_bytes))
                cf_modlist_entries.append({
                    "title": m["title"],
                    "author": m["author"],
                    "page_url": m["page_url"] or f"https://modrinth.com/mod/{m['slug']}"
                })

        # Populate Modrinth modrinth.index.json entry or fallback to MR overrides/mods/
        if mr_info and mr_info.get("url", "").startswith("https://cdn.modrinth.com/"):
            hashes = mr_info.get("hashes", {})
            sha1_val = hashes.get("sha1") or hashlib.sha1(jar_bytes).hexdigest()
            sha512_val = hashes.get("sha512") or hashlib.sha512(jar_bytes).hexdigest()
            env_dict = {
                "client": "required" if side in ["client", "both"] else "unsupported",
                "server": "required" if side in ["server", "both"] else "unsupported"
            }
            mr_index_files.append({
                "path": f"mods/{fname}",
                "hashes": {
                    "sha1": sha1_val,
                    "sha512": sha512_val
                },
                "env": env_dict,
                "downloads": [mr_info["url"]],
                "fileSize": len(jar_bytes)
            })
        else:
            if side in ["client", "both"]:
                mr_override_mods.append((fname, jar_bytes))

    server_mods = [(d["filename"], d["bytes"], d["side"]) for d in downloaded if d["side"] in ["server", "both"]]
    client_mods = [(d["filename"], d["bytes"], d["side"]) for d in downloaded if d["side"] in ["client", "both"]]
    safe_pack_name = pack_name.replace(" ", "_")

    # Direct CurseForge Modpack Export (.zip)
    if export_target == "curseforge":
        cf_bytes = build_curseforge_pack_bytes(
            pack_name=pack_name,
            mc_version=mc_version,
            loader=loader,
            loader_version=loader_version,
            cf_manifest_files=cf_manifest_files,
            modlist_entries=cf_modlist_entries,
            override_mods=cf_override_mods
        )
        return StreamingResponse(
            io.BytesIO(cf_bytes),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={safe_pack_name}-curseforge.zip"}
        )

    # Direct Modrinth Modpack Export (.mrpack)
    if export_target == "modrinth":
        mr_bytes = build_modrinth_mrpack_bytes(
            pack_name=pack_name,
            mc_version=mc_version,
            loader=loader,
            loader_version=loader_version,
            mr_index_files=mr_index_files,
            override_mods=mr_override_mods
        )
        return StreamingResponse(
            io.BytesIO(mr_bytes),
            media_type="application/x-modrinth-modpack+zip",
            headers={"Content-Disposition": f"attachment; filename={safe_pack_name}.mrpack"}
        )

    out_buffer = io.BytesIO()
    with zipfile.ZipFile(out_buffer, 'w', zipfile.ZIP_DEFLATED) as out_zip:
        if export_target == "dual":
            # 1. Ready-to-upload CurseForge Modpack Archive
            cf_bytes = build_curseforge_pack_bytes(
                pack_name=pack_name,
                mc_version=mc_version,
                loader=loader,
                loader_version=loader_version,
                cf_manifest_files=cf_manifest_files,
                modlist_entries=cf_modlist_entries,
                override_mods=cf_override_mods
            )
            out_zip.writestr(f"curseforge/{safe_pack_name}-curseforge.zip", cf_bytes)

            # 2. Ready-to-upload Modrinth .mrpack Archive
            mr_bytes = build_modrinth_mrpack_bytes(
                pack_name=pack_name,
                mc_version=mc_version,
                loader=loader,
                loader_version=loader_version,
                mr_index_files=mr_index_files,
                override_mods=mr_override_mods
            )
            out_zip.writestr(f"modrinth/{safe_pack_name}.mrpack", mr_bytes)

            # 3. Unpacked Client Folder (for direct manual copy)
            for fname, fbytes, _ in client_mods:
                out_zip.writestr(f"client/mods/{fname}", fbytes)

            client_readme = f"""==================================================
  {pack_name} - CLIENT MODPACK (MC {mc_version} {loader.upper()} {loader_version})
==================================================
This folder is for PLAYERS to install in their launcher.

OPTION A - Import via Launcher (Recommended):
- Use 'curseforge/{safe_pack_name}-curseforge.zip' in CurseForge App / Prism Launcher
- Or use 'modrinth/{safe_pack_name}.mrpack' in Modrinth App / Prism Launcher

OPTION B - Manual Mods Folder Copy:
1. Create an instance for Minecraft {mc_version} ({loader.upper()} {loader_version}).
2. Copy all files from 'client/mods/' into your instance's 'mods/' directory.

Total Client Mods: {len(client_mods)}
"""
            out_zip.writestr("client/README.txt", client_readme)

            # 4. Unpacked Dedicated Server Folder
            for fname, fbytes, _ in server_mods:
                out_zip.writestr(f"server/mods/{fname}", fbytes)

            props = generate_server_properties(pack_name, port=port)
            out_zip.writestr("server/server.properties", props)
            out_zip.writestr("server/eula.txt", "eula=true\n")

            scripts = generate_run_scripts(loader, mc_version, memory_gb=ram_gb)
            for sname, scontent in scripts.items():
                out_zip.writestr(f"server/{sname}", scontent)

            server_readme = f"""==================================================
  {pack_name} - DEDICATED SERVER (MC {mc_version} {loader.upper()} {loader_version})
==================================================
This folder is for HOSTING the dedicated multiplayer server (or uploading to CurseForge as an Additional Server Pack).

HOW TO RUN:
- Linux / Bare Metal:   chmod +x run.sh && ./run.sh
- Windows Bare Metal:   Double-click run.bat
- Docker / Proxmox:     docker-compose up -d

Allocated RAM:     {ram_gb} GB (Aikar G1GC Flags)
Total Server Mods: {len(server_mods)}
"""
            out_zip.writestr("server/README.txt", server_readme)

            # 5. Root Upload & Installation Guide
            root_readme = f"""# {pack_name} — Complete Distribution Bundle

Minecraft: `{mc_version}` | Loader: `{loader.upper()} ({loader_version})`

This bundle includes ready-to-upload packages for **CurseForge**, **Modrinth**, **Players**, and **Dedicated Servers**:

1. **Upload to CurseForge (`curseforge/{safe_pack_name}-curseforge.zip`)**:
   - Contains root `manifest.json`, `modlist.html`, and `overrides/` strictly formatted to the CurseForge Modpack specification.
   - Upload directly at `https://legacy.curseforge.com/minecraft/modpacks/create` or import directly into the CurseForge App.

2. **Upload to Modrinth (`modrinth/{safe_pack_name}.mrpack`)**:
   - Contains root `modrinth.index.json` (formatVersion 1) with SHA-1/SHA-512 hashes and `overrides/`.
   - Upload directly to Modrinth or import into Modrinth App / Prism Launcher.

3. **Client Folder (`client/mods/`)**:
   - Pre-downloaded `.jar` files for players who want to drag-and-drop directly into `.minecraft/mods/`.

4. **Dedicated Server Folder (`server/`)**:
   - Stripped of client-only mods, pre-configured with `server.properties`, `eula.txt`, `run.sh`, `run.bat`, and Docker support.

---
Compatibility Status:
{report.summary}
"""
            out_zip.writestr("README.md", root_readme)
            filename = f"{safe_pack_name}-dual-pack.zip"

        elif export_target == "client":
            # Client pack with manifest.json + modlist.html + mods/ so it works everywhere
            cf_loader_id = f"{loader.lower()}-{loader_version}"
            manifest = {
                "minecraft": {
                    "version": mc_version,
                    "modLoaders": [{"id": cf_loader_id, "primary": True}]
                },
                "manifestType": "minecraftModpack",
                "manifestVersion": 1,
                "name": pack_name,
                "version": "1.0.0",
                "author": "Protutech",
                "files": cf_manifest_files,
                "overrides": "overrides"
            }
            out_zip.writestr("manifest.json", json.dumps(manifest, indent=2))
            for fname, fbytes, _ in client_mods:
                out_zip.writestr(f"mods/{fname}", fbytes)
                out_zip.writestr(f"overrides/mods/{fname}", fbytes)

            client_readme = f"""==================================================
  {pack_name} - CLIENT MODPACK (MC {mc_version} {loader.upper()} {loader_version})
==================================================
Install this into CurseForge, Prism Launcher, Modrinth App, or copy 'mods/' into your Minecraft directory.
Total Mods: {len(client_mods)}
"""
            out_zip.writestr("README.txt", client_readme)
            filename = f"{safe_pack_name}-client.zip"

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
Loader:            {loader.upper()} ({loader_version})
Allocated RAM:     {ram_gb} GB

COMPATIBILITY STATUS:
{report.summary}

INCLUDED SERVER MODS ({len(server_mods)}):
"""
            for fname, _, _ in server_mods:
                summary_txt += f" + {fname}\n"

            out_zip.writestr("PACK_INFO.txt", summary_txt)
            filename = f"{safe_pack_name}-server-pack.zip"

    out_buffer.seek(0)
    if stage_for_discopanel:
        package_id = str(uuid.uuid4())
        staged_path = os.path.join(DISCO_STAGE_DIR, f"{package_id}.zip")
        with open(staged_path, "wb") as f:
            f.write(out_buffer.getvalue())
        return {
            "status": "staged",
            "package_id": package_id,
            "download_path": f"/api/disco-download/{package_id}.zip",
            "pack_name": pack_name,
            "loader": loader,
            "mc_version": mc_version,
            "ram_gb": ram_gb,
            "port": port,
            "java_info": get_java_runtime_for_mc(mc_version)
        }

    return StreamingResponse(
        out_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/disco-download/{package_id}.zip")
async def api_disco_download(package_id: str):
    """Serves a staged server package directly to root@discopanel via curl or SFTP."""
    safe_id = os.path.basename(package_id)
    staged_path = os.path.join(DISCO_STAGE_DIR, f"{safe_id}.zip")
    if not os.path.exists(staged_path):
        raise HTTPException(status_code=404, detail="Staged DiscoPanel package not found or expired")
    return FileResponse(staged_path, media_type="application/zip", filename=f"{safe_id}.zip")

@app.post("/api/discopanel/test-connection")
async def api_test_discopanel_connection(
    host: str = Form("192.168.0.119"),
    port: int = Form(22),
    username: str = Form("root"),
    password: str = Form(None),
    private_key: str = Form(None),
    passphrase: str = Form(None)
):
    """Verifies direct SSH connectivity to DiscoPanel host (Docker, DB, disk, and permissions)."""
    return test_discopanel_connection(
        host=host,
        port=port,
        username=username,
        password=password if password and password.strip() else None,
        private_key=private_key if private_key and private_key.strip() else None,
        passphrase=passphrase if passphrase and passphrase.strip() else None,
        timeout=8
    )

@app.post("/api/inspect-world")
async def api_inspect_world(world_file: UploadFile = File(...)):
    """Deeply inspects an uploaded singleplayer world save and extracts metadata, chunks, and dimensions."""
    content = await world_file.read()
    if not (world_file.filename.endswith(".zip") or world_file.filename.endswith(".tar.gz")):
        raise HTTPException(status_code=400, detail="World save must be a .zip archive containing level.dat")
    info = inspect_world_save(content)
    return info

@app.post("/api/discopanel/deploy")
async def api_deploy_to_discopanel(
    host: str = Form("192.168.0.119"),
    port: int = Form(22),
    username: str = Form("root"),
    password: str = Form(None),
    private_key: str = Form(None),
    passphrase: str = Form(None),
    server_name: str = Form("Minecraft Server"),
    loader: str = Form("fabric"),
    mc_version: str = Form("1.20.1"),
    ram_gb: int = Form(6),
    server_port: int = Form(25565),
    staged_package_id: str = Form(None),
    world_file: UploadFile = File(None)
):
    """
    Automated direct 1-click deployment to DiscoPanel host.
    Connects via SSH/SFTP, uploads server bundle & world save, provisions Docker container,
    and registers instance in DiscoPanel SQLite database.
    """
    server_zip_bytes = None
    if staged_package_id:
        safe_id = os.path.basename(staged_package_id)
        staged_path = os.path.join(DISCO_STAGE_DIR, f"{safe_id}.zip")
        if os.path.exists(staged_path):
            with open(staged_path, "rb") as f:
                server_zip_bytes = f.read()

    world_zip_bytes = None
    if world_file and world_file.filename:
        raw_world = await world_file.read()
        if len(raw_world) > 0:
            world_info = inspect_world_save(raw_world)
            if world_info.get("valid"):
                world_zip_bytes = normalize_world_save_zip(raw_world)
            else:
                world_zip_bytes = raw_world

    java_info = get_java_runtime_for_mc(mc_version)

    deploy_res = deploy_to_discopanel_host(
        host=host,
        port=port,
        username=username,
        password=password if password and password.strip() else None,
        private_key=private_key if private_key and private_key.strip() else None,
        passphrase=passphrase if passphrase and passphrase.strip() else None,
        server_name=server_name,
        loader=loader,
        mc_version=mc_version,
        ram_gb=ram_gb,
        server_port=server_port,
        server_zip_bytes=server_zip_bytes,
        world_zip_bytes=world_zip_bytes
    )
    deploy_res["java_runtime"] = java_info
    return deploy_res

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
    additional_only: bool = Form(False),
    stage_for_discopanel: bool = Form(False)
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

    loader_version = analysis.loader_version or resolve_loader_version(analysis.loader, analysis.minecraft_version)
    safe_pack_name = analysis.pack_name.replace(" ", "_")

    # Helper to normalize source paths
    def normalize_path(raw_name: str) -> str:
        path = raw_name
        if path.startswith("overrides/"):
            path = path.replace("overrides/", "", 1)
        elif path.startswith(".minecraft/"):
            path = path.replace(".minecraft/", "", 1)
        return path

    # Prepare CurseForge & Modrinth client export data from the existing archive
    cf_manifest_files = []
    mr_index_files = []
    if analysis.pack_type == "curseforge" and isinstance(analysis.raw_manifest, dict):
        cf_manifest_files = analysis.raw_manifest.get("files", [])
    elif analysis.pack_type == "modrinth" and isinstance(analysis.raw_manifest, dict):
        mr_index_files = analysis.raw_manifest.get("files", [])

    extra_overrides = {}
    for item in src_zip.infolist():
        if item.is_dir():
            continue
        if item.filename in ["manifest.json", "modlist.html", "modrinth.index.json"]:
            continue
        norm_p = normalize_path(item.filename)
        if norm_p:
            extra_overrides[norm_p] = src_zip.read(item.filename)

    if export_target == "curseforge":
        cf_bytes = build_curseforge_pack_bytes(
            pack_name=analysis.pack_name,
            mc_version=analysis.minecraft_version,
            loader=analysis.loader,
            loader_version=loader_version,
            cf_manifest_files=cf_manifest_files,
            modlist_entries=[{"title": m["name"], "author": "Mod Author", "page_url": "#"} for m in analysis.server_mods_kept + analysis.client_mods_removed],
            override_mods=[],
            extra_overrides=extra_overrides
        )
        return StreamingResponse(
            io.BytesIO(cf_bytes),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={safe_pack_name}-curseforge.zip"}
        )

    if export_target == "modrinth":
        mr_bytes = build_modrinth_mrpack_bytes(
            pack_name=analysis.pack_name,
            mc_version=analysis.minecraft_version,
            loader=analysis.loader,
            loader_version=loader_version,
            mr_index_files=mr_index_files,
            override_mods=[],
            extra_overrides=extra_overrides
        )
        return StreamingResponse(
            io.BytesIO(mr_bytes),
            media_type="application/x-modrinth-modpack+zip",
            headers={"Content-Disposition": f"attachment; filename={safe_pack_name}.mrpack"}
        )

    # Build the package according to export_target ('dual', 'client', or 'server'):
    with zipfile.ZipFile(out_buffer, 'w', zipfile.ZIP_DEFLATED) as out_zip:
        removed_filenames = {m["filename"] for m in analysis.client_mods_removed}

        props_content = generate_server_properties(analysis.pack_name, port=port)
        scripts = generate_run_scripts(analysis.loader, analysis.minecraft_version, memory_gb=ram_gb)

        conversion_report = f"""==================================================
  MINECRAFT SERVER CONVERSION REPORT
==================================================
Modpack Name:      {analysis.pack_name}
Minecraft Version: {analysis.minecraft_version}
Loader:            {analysis.loader.upper()} ({loader_version})
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
            # --- 1. Ready-to-upload CurseForge & Modrinth packages ---
            cf_bytes = build_curseforge_pack_bytes(
                pack_name=analysis.pack_name,
                mc_version=analysis.minecraft_version,
                loader=analysis.loader,
                loader_version=loader_version,
                cf_manifest_files=cf_manifest_files,
                modlist_entries=[{"title": m["name"], "author": "Mod Author", "page_url": "#"} for m in analysis.server_mods_kept + analysis.client_mods_removed],
                override_mods=[],
                extra_overrides=extra_overrides
            )
            out_zip.writestr(f"curseforge/{safe_pack_name}-curseforge.zip", cf_bytes)

            mr_bytes = build_modrinth_mrpack_bytes(
                pack_name=analysis.pack_name,
                mc_version=analysis.minecraft_version,
                loader=analysis.loader,
                loader_version=loader_version,
                mr_index_files=mr_index_files,
                override_mods=[],
                extra_overrides=extra_overrides
            )
            out_zip.writestr(f"modrinth/{safe_pack_name}.mrpack", mr_bytes)

            # --- 2. Unpacked Client Folder ---
            for item in src_zip.infolist():
                if item.is_dir():
                    continue
                target_path = normalize_path(item.filename)
                if target_path:
                    out_zip.writestr(f"client/{target_path}", src_zip.read(item.filename))

            client_readme = f"""{analysis.pack_name} - Client Modpack
Minecraft: {analysis.minecraft_version} | Loader: {analysis.loader.upper()} ({loader_version})

This folder is for PLAYERS to install in their launcher.
Copy 'client/mods' (and configs/resourcepacks) into your Minecraft client directory,
or import 'curseforge/{safe_pack_name}-curseforge.zip' or 'modrinth/{safe_pack_name}.mrpack' directly into your launcher.
"""
            out_zip.writestr("client/README.txt", client_readme)

            # --- 3. Unpacked Server Folder ---
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

            # --- 4. Root README ---
            root_readme = f"""# {analysis.pack_name} (Complete Distribution Bundle)

Minecraft: `{analysis.minecraft_version}` | Loader: `{analysis.loader.upper()} ({loader_version})`

This archive contains separated distributions for CurseForge, Modrinth, players, and the dedicated server:

1. **`curseforge/{safe_pack_name}-curseforge.zip`**: Ready to upload to CurseForge or import into CurseForge App.
2. **`modrinth/{safe_pack_name}.mrpack`**: Ready to upload to Modrinth or import into Modrinth App / Prism Launcher.
3. **`client/`** (For Players): Unpacked client mods, shaders, HUDs, and client configurations.
4. **`server/`** (For Dedicated Server): Stripped server mods with client-crashing mods removed, injected performance mods, `server.properties`, `eula.txt`, `run.sh` / `run.bat`, and Docker files.
"""
            out_zip.writestr("README.md", root_readme)
            out_filename = f"{safe_pack_name}-dual-pack.zip"

        elif export_target == "client":
            # Client Only
            for item in src_zip.infolist():
                if item.is_dir():
                    continue
                target_path = normalize_path(item.filename)
                if target_path:
                    out_zip.writestr(target_path, src_zip.read(item.filename))

            client_readme = f"""{analysis.pack_name} - Client Modpack
Minecraft: {analysis.minecraft_version} | Loader: {analysis.loader.upper()} ({loader_version})
Copy this directory into your Minecraft launcher instance.
"""
            out_zip.writestr("README.txt", client_readme)
            out_filename = f"{safe_pack_name}-client-pack.zip"

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
            out_filename = f"{safe_pack_name}-server-pack.zip"

    out_buffer.seek(0)
    if stage_for_discopanel:
        package_id = str(uuid.uuid4())
        staged_path = os.path.join(DISCO_STAGE_DIR, f"{package_id}.zip")
        with open(staged_path, "wb") as f:
            f.write(out_buffer.getvalue())
        return {
            "status": "staged",
            "package_id": package_id,
            "download_path": f"/api/disco-download/{package_id}.zip",
            "pack_name": analysis.pack_name,
            "loader": analysis.loader,
            "mc_version": analysis.minecraft_version,
            "ram_gb": ram_gb,
            "port": port,
            "java_info": get_java_runtime_for_mc(analysis.minecraft_version)
        }

    return StreamingResponse(
        out_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={out_filename}"}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8080, reload=True)

