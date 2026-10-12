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

def get_all_minecraft_versions() -> List[str]:
    """Fetches all official Minecraft release versions from Modrinth API."""
    try:
        url = f"{MODRINTH_API}/tag/game_version"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            releases = [
                v["version"] for v in data 
                if v.get("version_type") == "release"
            ]
            return releases
    except Exception as e:
        logger.warning(f"Error fetching game versions: {e}")
    # Comprehensive fallback
    return [
        "1.21.4", "1.21.3", "1.21.2", "1.21.1", "1.21", 
        "1.20.6", "1.20.5", "1.20.4", "1.20.2", "1.20.1", "1.20",
        "1.19.4", "1.19.3", "1.19.2", "1.19.1", "1.19",
        "1.18.2", "1.18.1", "1.18", "1.17.1", "1.16.5", "1.12.2", "1.7.10"
    ]

def search_version_mods(
    query: str = "",
    mc_version: str = "1.20.1",
    loader: str = "fabric",
    provider: str = "all",
    api_key: str = None,
    limit: int = 24
) -> List[Dict[str, Any]]:
    """
    Searches for individual mods strictly filtered to the chosen Minecraft version & loader.
    """
    results = []

    # 1. Modrinth Search with strict version & loader facets
    if provider in ["all", "modrinth"]:
        try:
            url = f"{MODRINTH_API}/search"
            # Map loader
            loader_val = loader.lower()
            if loader_val == "quilt":
                loader_facets = ["categories:quilt", "categories:fabric"]
            else:
                loader_facets = [f"categories:{loader_val}"]

            facets = [
                ["project_type:mod"],
                loader_facets,
                [f"versions:{mc_version}"]
            ]

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
                for h in hits:
                    results.append({
                        "id": h.get("project_id"),
                        "slug": h.get("slug"),
                        "title": h.get("title"),
                        "description": h.get("description"),
                        "icon_url": h.get("icon_url"),
                        "author": h.get("author"),
                        "downloads": h.get("downloads", 0),
                        "categories": h.get("categories", []),
                        "provider": "modrinth",
                        "page_url": f"https://modrinth.com/mod/{h.get('slug')}"
                    })
        except Exception as e:
            logger.warning(f"Error fetching version mods from Modrinth: {e}")

    # 2. CurseForge Search filtered by gameVersion & modLoaderType
    if provider in ["all", "curseforge"]:
        key = api_key or DEFAULT_CF_API_KEY
        if key:
            try:
                headers = {"x-api-key": key, "Accept": "application/json"}
                loader_type_map = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
                loader_type = loader_type_map.get(loader.lower(), 4)

                url = f"{CURSEFORGE_API}/mods/search"
                params = {
                    "gameId": 432,           # Minecraft
                    "classId": 6,            # Mods (not modpacks)
                    "gameVersion": mc_version,
                    "modLoaderType": loader_type,
                    "pageSize": limit,
                    "sortField": 2,          # Popularity
                    "sortOrder": "desc"
                }
                if query:
                    params["searchFilter"] = query

                res = requests.get(url, headers=headers, params=params, timeout=6)
                if res.status_code == 200:
                    data = res.json().get("data", [])
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
                            "downloads": d.get("downloadCount", 0),
                            "provider": "curseforge",
                            "page_url": d.get("links", {}).get("websiteUrl") or f"https://www.curseforge.com/minecraft/mc-mods/{d.get('slug')}"
                        })
            except Exception as e:
                logger.warning(f"Error fetching version mods from CurseForge: {e}")

    return results
