"""
Catalog of known client-side only mods and recommended server-side performance mods.
"""

# Client-only mods that cause server crashes (ClassNotFound, PhysicalSide, etc.)
# or are completely useless on dedicated servers (minimaps, shaders, sound, GUI, zoom, etc.)
KNOWN_CLIENT_MODS = {
    # Shaders & Rendering Engines
    "sodium", "rubidium", "embeddium", "iris", "oculus", "optifine", "magnesium", 
    "indium", "xenon", "continuity", "entityculling", "entity_culling", "cullleaves", 
    "cull-leaves", "immediatelyfast", "immediately-fast", "dynamic_fps", "dynamicfps", 
    "reeses-sodium-options", "sodium-extra", "flashback", "distanthorizons", "distant-horizons",
    "bobby", "lambdynlights", "lambdynamiclights", "visuality", "fallingleaves", "notenoughanimations",
    "waveycapes", "customselectionbox", "trajan-core", "presencefootsteps",

    # Minimaps & HUDs
    "journeymap", "xaerominimap", "xaeros_minimap", "xaeroworldmap", "xaeros_world_map", 
    "voxelmap", "mapwriter", "antiqueatlas", "jade", "wthit", "hwyla", "waila", 
    "appleskin", "inventoryhud", "inventory-hud-plus", "neat", "torohealth", "betterf3", 
    "shulkerboxtooltip", "light-overlay", "lightoverlay", "modmenu", "catalogue",

    # Recipe viewers client side integrations (JEI/REI/EMI can run on server, but purely client UI add-ons)
    "roughlyenoughprofessions", "justenoughresources", "jer", "jei-integration", 

    # Sound & Audio
    "soundphysics", "sound-physics-remastered", "presence-footsteps", "dynamic-music", 
    "ambient-sounds", "ambientsounds", "auditory", "music-player",

    # Camera & Zoom & Controls
    "zoomify", "okzoomer", "wi-zoom", "logical-zoom", "controlling", "searchables",
    "item-borders", "borderless-mining", "borderlessmining", "custom-crosshair-mod",
    "screenshot-viewer", "replaymod", "freecam", "cameraoverhaul", "mousewheelie",
    "itemphysic-lite", "blur", "blur-fabric", "smoothboot", "smooth-boot", "lazydfu",
    "dashloader", "farsight", "tips", "tipthescales", "legendarytooltips",

    # Screen & Chat
    "chat-heads", "chatheads", "clear-chat", "toast-control", "craftingtweaks"
}

# Catalog of verified server-side only performance and optimization mods
SERVER_PERFORMANCE_CATALOG = {
    "fabric": {
        "lithium": {
            "name": "Lithium",
            "mod_id": "lithium",
            "project_id": "lithium",
            "description": "General physics, chunk loading, and mob AI optimization. 100% vanilla parity.",
            "category": "Core Performance",
            "recommended": True
        },
        "ferritecore": {
            "name": "FerriteCore",
            "mod_id": "ferritecore",
            "project_id": "ferrite-core",
            "description": "Massively reduces server memory/RAM usage without altering gameplay.",
            "category": "Memory / RAM",
            "recommended": True
        },
        "krypton": {
            "name": "Krypton",
            "mod_id": "krypton",
            "project_id": "krypton",
            "description": "Optimizes the Minecraft networking stack to lower player ping and reduce bandwidth.",
            "category": "Network",
            "recommended": True
        },
        "c2me": {
            "name": "C2ME (Concurrent Chunk Management)",
            "mod_id": "c2me",
            "project_id": "c2me-fabric",
            "description": "Multithreads chunk generation and I/O. Drastically reduces Elytra & exploration lag.",
            "category": "World Gen & Chunks",
            "recommended": True
        },
        "modernfix": {
            "name": "ModernFix",
            "mod_id": "modernfix",
            "project_id": "modernfix",
            "description": "Fixes numerous vanilla memory leaks, speeds up loading times, and enhances performance.",
            "category": "Core & Bugfix",
            "recommended": True
        },
        "chunky": {
            "name": "Chunky",
            "mod_id": "chunky",
            "project_id": "chunky",
            "description": "Allows pre-generating your world chunks in advance to prevent in-game lag spikes.",
            "category": "Utilities",
            "recommended": True
        },
        "spark": {
            "name": "spark",
            "mod_id": "spark",
            "project_id": "spark",
            "description": "High-performance CPU and memory profiler to diagnose exactly what causes tick lag.",
            "category": "Diagnostics",
            "recommended": False
        },
        "ledger": {
            "name": "Ledger",
            "mod_id": "ledger",
            "project_id": "ledger",
            "description": "Server-side block logging, inspection, and grief rollback (CoreProtect equivalent).",
            "category": "Administration",
            "recommended": False
        },
        "servux": {
            "name": "Servux",
            "mod_id": "servux",
            "project_id": "servux",
            "description": "Server-side companion mod providing structure bounding boxes to clients (MiniHUD/Litematica).",
            "category": "Client Companion",
            "recommended": False
        }
    },
    "forge": {
        "ferritecore": {
            "name": "FerriteCore",
            "mod_id": "ferritecore",
            "project_id": "ferrite-core",
            "description": "Massively reduces server memory/RAM usage without altering gameplay.",
            "category": "Memory / RAM",
            "recommended": True
        },
        "modernfix": {
            "name": "ModernFix",
            "mod_id": "modernfix",
            "project_id": "modernfix",
            "description": "Fixes numerous vanilla memory leaks and speeds up launch & execution.",
            "category": "Core & Bugfix",
            "recommended": True
        },
        "canary": {
            "name": "Canary (Lithium Port)",
            "mod_id": "canary",
            "project_id": "canary",
            "description": "Forge port of Lithium optimizing physics, AI, and block ticking.",
            "category": "Core Performance",
            "recommended": True
        },
        "radon": {
            "name": "Radon (Phosphor/Starlight Port)",
            "mod_id": "radon",
            "project_id": "radon",
            "description": "Lighting engine performance enhancements for older Forge releases.",
            "category": "Lighting",
            "recommended": False
        },
        "chunky": {
            "name": "Chunky",
            "mod_id": "chunky",
            "project_id": "chunky",
            "description": "Pre-generate terrain before players join to eliminate chunk gen stutters.",
            "category": "Utilities",
            "recommended": True
        },
        "spark": {
            "name": "spark",
            "mod_id": "spark",
            "project_id": "spark",
            "description": "High-performance CPU and memory profiler to diagnose tick lag.",
            "category": "Diagnostics",
            "recommended": False
        }
    },
    "neoforge": {
        "ferritecore": {
            "name": "FerriteCore",
            "mod_id": "ferritecore",
            "project_id": "ferrite-core",
            "description": "Massively reduces server memory/RAM usage without altering gameplay.",
            "category": "Memory / RAM",
            "recommended": True
        },
        "modernfix": {
            "name": "ModernFix",
            "mod_id": "modernfix",
            "project_id": "modernfix",
            "description": "Fixes numerous vanilla memory leaks and speeds up loading & tick time.",
            "category": "Core & Bugfix",
            "recommended": True
        },
        "chunky": {
            "name": "Chunky",
            "mod_id": "chunky",
            "project_id": "chunky",
            "description": "Pre-generate terrain before players join to eliminate chunk gen stutters.",
            "category": "Utilities",
            "recommended": True
        },
        "spark": {
            "name": "spark",
            "mod_id": "spark",
            "project_id": "spark",
            "description": "High-performance CPU and memory profiler to diagnose tick lag.",
            "category": "Diagnostics",
            "recommended": False
        }
    }
}
