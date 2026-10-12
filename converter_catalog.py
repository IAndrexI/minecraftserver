"""
Expanded Catalog of Performance, Optimization, Utility, Admin, and Security mods.
"""

# Client-only mods that cause server crashes (ClassNotFound, PhysicalSide, etc.)
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

    # Recipe viewers client side integrations
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

# Known conflicting mod pairs (mutually exclusive)
MOD_CONFLICTS = [
    ({"sodium", "rubidium", "embeddium"}, "Conflicting rendering engines"),
    ({"c2me", "chunky-border"}, "Overlapping chunk boundary controllers"),
    ({"starlight", "phosphor", "radon"}, "Conflicting lighting engines"),
    ({"lithium", "canary"}, "Duplicate physics engines (Canary is a port of Lithium)"),
    ({"simple-voice-chat", "plasmo-voice"}, "Multiple voice chat systems active simultaneously")
]

# Comprehensive Catalog of verified server-side mods categorized
EXPANDED_SERVER_MODS_CATALOG = {
    "fabric": [
        # --- Performance & Core Optimization ---
        {
            "name": "Lithium",
            "mod_id": "lithium",
            "project_id": "lithium",
            "description": "General physics, chunk loading, and mob AI optimization. 100% vanilla parity.",
            "category": "Performance: Core",
            "recommended": True
        },
        {
            "name": "FerriteCore",
            "mod_id": "ferritecore",
            "project_id": "ferrite-core",
            "description": "Massively reduces server memory/RAM usage without altering gameplay.",
            "category": "Performance: Memory",
            "recommended": True
        },
        {
            "name": "Krypton",
            "mod_id": "krypton",
            "project_id": "krypton",
            "description": "Optimizes Minecraft networking stack to lower latency and bandwidth.",
            "category": "Performance: Network",
            "recommended": True
        },
        {
            "name": "C2ME",
            "mod_id": "c2me",
            "project_id": "c2me-fabric",
            "description": "Multithreads chunk generation and I/O. Reduces Elytra & exploration lag.",
            "category": "Performance: Chunks",
            "recommended": True
        },
        {
            "name": "ModernFix",
            "mod_id": "modernfix",
            "project_id": "modernfix",
            "description": "Fixes numerous vanilla memory leaks, speeds up loading times & tick time.",
            "category": "Performance: Core",
            "recommended": True
        },
        {
            "name": "MemoryLeakFix",
            "mod_id": "memoryleakfix",
            "project_id": "memoryleakfix",
            "description": "Patches multiple memory leaks in Minecraft client and server code.",
            "category": "Performance: Memory",
            "recommended": True
        },
        {
            "name": "Concurrent Chunk Management",
            "mod_id": "vmp",
            "project_id": "vmp-fabric",
            "description": "Very Many Players (VMP): Optimizes entity tracking and player networking for busy servers.",
            "category": "Performance: Entities",
            "recommended": False
        },
        {
            "name": "Carpet Mod",
            "mod_id": "carpet",
            "project_id": "carpet",
            "description": "Technical Minecraft server mod for tick profiling, mob spawning controls, and farm debugging.",
            "category": "Technical & Diagnostics",
            "recommended": False
        },

        # --- Utility & Administration ---
        {
            "name": "Chunky",
            "mod_id": "chunky",
            "project_id": "chunky",
            "description": "Pre-generates world chunks in advance to prevent in-game exploration lag spikes.",
            "category": "Utility: World Gen",
            "recommended": True
        },
        {
            "name": "Chunky Border",
            "mod_id": "chunky-border",
            "project_id": "chunky-border",
            "description": "Enforces a clean world border compatible with Chunky pre-generation.",
            "category": "Utility: World Gen",
            "recommended": False
        },
        {
            "name": "spark",
            "mod_id": "spark",
            "project_id": "spark",
            "description": "High-performance CPU profiler and memory inspector to find exact lag causes.",
            "category": "Administration: Diagnostics",
            "recommended": True
        },
        {
            "name": "Ledger",
            "mod_id": "ledger",
            "project_id": "ledger",
            "description": "Server-side block logging, inspection, and grief rollback (CoreProtect equivalent).",
            "category": "Administration: Anti-Grief",
            "recommended": False
        },
        {
            "name": "Fabric Permissions API",
            "mod_id": "fabric-permissions-api-v0",
            "project_id": "fabric-permissions-api",
            "description": "Permits LuckPerms or other permission managers to hook into modded commands.",
            "category": "Administration: Permissions",
            "recommended": False
        },
        {
            "name": "LuckPerms",
            "mod_id": "luckperms",
            "project_id": "luckperms",
            "description": "Industry standard permissions and rank management plugin/mod.",
            "category": "Administration: Permissions",
            "recommended": False
        },
        {
            "name": "Simple Voice Chat",
            "mod_id": "voicechat",
            "project_id": "simple-voice-chat",
            "description": "Proximity voice chat on the server with distance attenuation and Opus encoding.",
            "category": "Gameplay: Voice",
            "recommended": False
        },
        {
            "name": "Servux",
            "mod_id": "servux",
            "project_id": "servux",
            "description": "Server companion sending structure bounding boxes to clients (MiniHUD/Litematica).",
            "category": "Utility: Client Companion",
            "recommended": False
        },
        {
            "name": "Dynmap",
            "mod_id": "dynmap",
            "project_id": "dynmap",
            "description": "Real-time Google-Maps style web map of your Minecraft world in your browser.",
            "category": "Utility: Web Map",
            "recommended": False
        },
        {
            "name": "BlueMap",
            "mod_id": "bluemap",
            "project_id": "bluemap",
            "description": "Photorealistic 3D web map rendered with WebGL for your server.",
            "category": "Utility: Web Map",
            "recommended": False
        }
    ],
    "forge": [
        {
            "name": "FerriteCore",
            "mod_id": "ferritecore",
            "project_id": "ferrite-core",
            "description": "Massively reduces server memory/RAM usage without altering gameplay.",
            "category": "Performance: Memory",
            "recommended": True
        },
        {
            "name": "ModernFix",
            "mod_id": "modernfix",
            "project_id": "modernfix",
            "description": "Fixes vanilla memory leaks and accelerates launch times & runtime.",
            "category": "Performance: Core",
            "recommended": True
        },
        {
            "name": "Canary",
            "mod_id": "canary",
            "project_id": "canary",
            "description": "Forge port of Lithium optimizing general physics, block ticking, and mob AI.",
            "category": "Performance: Core",
            "recommended": True
        },
        {
            "name": "Radon",
            "mod_id": "radon",
            "project_id": "radon",
            "description": "Lighting engine performance enhancements for older Forge releases.",
            "category": "Performance: Lighting",
            "recommended": False
        },
        {
            "name": "Chunky",
            "mod_id": "chunky",
            "project_id": "chunky",
            "description": "Pre-generates terrain before players join to eliminate chunk gen stutters.",
            "category": "Utility: World Gen",
            "recommended": True
        },
        {
            "name": "spark",
            "mod_id": "spark",
            "project_id": "spark",
            "description": "High-performance CPU and memory profiler to diagnose server tick lag.",
            "category": "Administration: Diagnostics",
            "recommended": True
        },
        {
            "name": "Simple Voice Chat",
            "mod_id": "voicechat",
            "project_id": "simple-voice-chat",
            "description": "Proximity voice chat on the server with distance attenuation.",
            "category": "Gameplay: Voice",
            "recommended": False
        },
        {
            "name": "FTB Chunks (Server)",
            "mod_id": "ftbchunks",
            "project_id": "ftb-chunks-forge",
            "description": "Claim chunks, chunkloading, and party team management.",
            "category": "Administration: Claims",
            "recommended": False
        }
    ],
    "neoforge": [
        {
            "name": "FerriteCore",
            "mod_id": "ferritecore",
            "project_id": "ferrite-core",
            "description": "Massively reduces server memory/RAM usage without altering gameplay.",
            "category": "Performance: Memory",
            "recommended": True
        },
        {
            "name": "ModernFix",
            "mod_id": "modernfix",
            "project_id": "modernfix",
            "description": "Fixes numerous vanilla memory leaks and speeds up loading & tick time.",
            "category": "Performance: Core",
            "recommended": True
        },
        {
            "name": "Chunky",
            "mod_id": "chunky",
            "project_id": "chunky",
            "description": "Pre-generates terrain before players join to eliminate chunk gen stutters.",
            "category": "Utility: World Gen",
            "recommended": True
        },
        {
            "name": "spark",
            "mod_id": "spark",
            "project_id": "spark",
            "description": "High-performance CPU and memory profiler to diagnose tick lag.",
            "category": "Administration: Diagnostics",
            "recommended": True
        },
        {
            "name": "Simple Voice Chat",
            "mod_id": "voicechat",
            "project_id": "simple-voice-chat",
            "description": "Proximity voice chat with position awareness.",
            "category": "Gameplay: Voice",
            "recommended": False
        }
    ]
}

# Quilt is fully compatible with Fabric server mods plus standard Quilt Standard Libraries (QSL)
EXPANDED_SERVER_MODS_CATALOG["quilt"] = EXPANDED_SERVER_MODS_CATALOG["fabric"]

# Alias for backwards compatibility
SERVER_PERFORMANCE_CATALOG = {
    loader: {m["mod_id"]: m for m in mods}
    for loader, mods in EXPANDED_SERVER_MODS_CATALOG.items()
}
