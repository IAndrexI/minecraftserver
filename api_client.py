"""
Client for querying modpacks and files from CurseForge and Modrinth APIs.
"""

import os
import re
import json
import logging
import requests
from typing import Dict, List, Optional, Any

logger = logging.getLogger("mc-api-client")

MODRINTH_API = "https://api.modrinth.com/v2"
CURSEFORGE_API = "https://api.curseforge.com/v1"

# Default CurseForge Key provided by the user
DEFAULT_CF_API_KEY = os.getenv("CF_API_KEY", "$2a$10$L4p7ZjoaaSXzBxrUGl8UXeSOEEKJWQJ5PoHVqwVbbTItG/4EPrmMK")

def search_modrinth_packs(query: str = "", limit: int = 24) -> List[Dict[str, Any]]:
    """Searches for modpacks on Modrinth, or gets popular ones if query is empty."""
    try:
        url = f"{MODRINTH_API}/search"
        facets = [["project_type:modpack"]]
        params = {
            "facets": json.dumps(facets),
            "limit": limit,
            "index": "downloads"
        }
        if query:
            params["query"] = query

        res = requests.get(url, params=params, timeout=6)
        if res.status_code == 200:
            hits = res.json().get("hits", [])
            results = []
            for h in hits:
                results.append({
                    "id": h.get("project_id"),
                    "slug": h.get("slug"),
                    "title": h.get("title"),
                    "description": h.get("description"),
                    "icon_url": h.get("icon_url"),
                    "author": h.get("author"),
                    "downloads": h.get("downloads", 0),
                    "versions": h.get("versions", []),
                    "categories": h.get("categories", []),
                    "provider": "modrinth",
                    "page_url": f"https://modrinth.com/modpack/{h.get('slug')}"
                })
            return results
    except Exception as e:
        logger.warning(f"Modrinth search error: {e}")
    return []

def search_curseforge_packs(query: str = "", api_key: str = None, limit: int = 24) -> List[Dict[str, Any]]:
    """Searches for modpacks on CurseForge using the v1 API."""
    key = api_key or DEFAULT_CF_API_KEY
    if not key:
        return []

    headers = {
        "x-api-key": key,
        "Accept": "application/json"
    }

    try:
        url = f"{CURSEFORGE_API}/mods/search"
        params = {
            "gameId": 432,           # Minecraft
            "classId": 4471,         # Modpacks
            "pageSize": limit,
            "sortField": 2,          # Popularity
            "sortOrder": "desc"
        }
        if query:
            params["searchFilter"] = query
        res = requests.get(url, headers=headers, params=params, timeout=6)
        if res.status_code == 200:
            data = res.json().get("data", [])
            results = []
            for d in data:
                logo = d.get("logo", {}) or {}
                authors = [a.get("name") for a in d.get("authors", [])]
                results.append({
                    "id": str(d.get("id")),
                    "slug": d.get("slug"),
                    "title": d.get("name"),
                    "description": d.get("summary"),
                    "icon_url": logo.get("thumbnailUrl") or logo.get("url"),
                    "author": ", ".join(authors) if authors else "Unknown",
                    "downloads": d.get("downloadCount"),
                    "provider": "curseforge",
                    "page_url": d.get("links", {}).get("websiteUrl") or f"https://www.curseforge.com/minecraft/modpacks/{d.get('slug')}"
                })
            return results
    except Exception as e:
        logger.warning(f"CurseForge search error: {e}")
    return []

def get_modrinth_versions(project_slug: str) -> List[Dict[str, Any]]:
    """Gets version list and direct download files for a Modrinth pack."""
    try:
        url = f"{MODRINTH_API}/project/{project_slug}/version"
        res = requests.get(url, timeout=6)
        if res.status_code == 200:
            versions = res.json()
            out = []
            for v in versions:
                files = v.get("files", [])
                primary = next((f for f in files if f.get("primary")), files[0] if files else None)
                if primary:
                    out.append({
                        "id": v.get("id"),
                        "name": v.get("name"),
                        "version_number": v.get("version_number"),
                        "game_versions": v.get("game_versions", []),
                        "loaders": v.get("loaders", []),
                        "download_url": primary.get("url"),
                        "filename": primary.get("filename")
                    })
            return out
    except Exception as e:
        logger.warning(f"Modrinth version lookup error: {e}")
    return []

def get_curseforge_versions(mod_id: str, api_key: str = None) -> List[Dict[str, Any]]:
    """Gets files/versions for a CurseForge modpack."""
    key = api_key or DEFAULT_CF_API_KEY
    if not key:
        return []

    headers = {
        "x-api-key": key,
        "Accept": "application/json"
    }

    try:
        url = f"{CURSEFORGE_API}/mods/{mod_id}/files"
        res = requests.get(url, headers=headers, timeout=6)
        if res.status_code == 200:
            files = res.json().get("data", [])
            out = []
            for f in files:
                out.append({
                    "id": str(f.get("id")),
                    "name": f.get("displayName"),
                    "filename": f.get("fileName"),
                    "game_versions": f.get("gameVersions", []),
                    "download_url": f.get("downloadUrl"),
                    "date": f.get("fileDate")
                })
            return out
    except Exception as e:
        logger.warning(f"CurseForge files lookup error: {e}")
    return []
