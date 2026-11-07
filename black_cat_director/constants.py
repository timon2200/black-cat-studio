# -*- coding: utf-8 -*-
"""
Black Cat Animation Director Studio v2.0 — Constants, Roster & Shared Helpers
=============================================================================
General-purpose Blender 4.x / 5.x Add-on & Python SDK for animating rigged
quadruped black cats with:
  - 180,000-strand 3D Feline Fur Coat (Furless in Viewport by default for fast
    animation playback, full 3D fur in Render) + Matte-Velvet Undercoat +
    Glossy Eye Mask + Whiskers Shader,
  - Zero-Slip 3D Curve Locomotion & Interactive Curve Drawing,
  - Multi-Clip NLA Animation Stacker & Editor,
  - Stray-Style Procedural Quadruped Biomechanics (Spine S-Bend, Tail Rudder,
    Head Anticipation, Blinks, Ear Twitches & Breathing).
"""

import glob
import json
import os
import shutil
import bpy


# ============================================================================
# 1. DYNAMIC PORTABLE PATH RESOLUTION
# ============================================================================

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
PACKAGE_DIR = os.path.dirname(ADDON_DIR)


def _load_studio_paths_config() -> dict:
    """Loads optional `_studio_paths.json` written by `install_cat_studio.py` when installed into Blender's addons folder."""
    cfg_path = os.path.join(ADDON_DIR, "_studio_paths.json")
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {}


def get_database_dir() -> str:
    """
    Resolves the `database/` directory dynamically so the add-on works portably
    from any `.blend` project on any machine:
      1. `BLACK_CAT_STUDIO_DIR` environment variable
      2. `_studio_paths.json` inside `black_cat_director/` (installed Blender Add-on)
      3. `<PACKAGE_DIR>/database` (adjacent to `black_cat_director/`)
      4. `<ADDON_DIR>/database` (packaged inside `black_cat_director/`)
      5. `<blend_dir>/black_cat_studio/database` or `<blend_dir>/database`
      6. Common user clone paths (`~/black-cat-studio/database`, etc.)
    """
    candidates = []
    env_root = os.environ.get("BLACK_CAT_STUDIO_DIR", "").strip()
    if env_root:
        candidates.append(os.path.join(env_root, "database"))

    cfg = _load_studio_paths_config()
    if cfg.get("database_dir"):
        candidates.append(cfg["database_dir"])
    if cfg.get("studio_root"):
        candidates.append(os.path.join(cfg["studio_root"], "database"))

    candidates.append(os.path.join(PACKAGE_DIR, "database"))
    candidates.append(os.path.join(ADDON_DIR, "database"))

    try:
        blend_path = getattr(bpy.data, "filepath", "") if bpy and hasattr(bpy, "data") else ""
        if blend_path:
            blend_dir = os.path.dirname(os.path.abspath(blend_path))
            candidates.append(os.path.join(blend_dir, "black_cat_studio", "database"))
            candidates.append(os.path.join(blend_dir, "database"))
    except Exception:
        pass

    home = os.path.expanduser("~")
    for sub in (
        "black-cat-studio",
        "Documents/black-cat-studio",
        "Desktop/black-cat-studio",
        "black_cat_studio",
        "Documents/black_cat_studio",
    ):
        candidates.append(os.path.join(home, sub, "database"))

    for cand in candidates:
        if cand and os.path.isdir(cand):
            lib_file = os.path.join(cand, "cat_assets_library.blend")
            part_file = os.path.join(cand, "cat_assets_library.blend.part01")
            reg_file = os.path.join(cand, "registry.json")
            if os.path.exists(lib_file) or os.path.exists(part_file) or os.path.exists(reg_file):
                return cand

    for cand in candidates:
        if cand and os.path.isdir(cand):
            return cand
    return os.path.join(PACKAGE_DIR, "database")


def get_studio_root() -> str:
    db_dir = get_database_dir()
    return os.path.dirname(db_dir)


def get_library_blend_path() -> str:
    """
    Returns the path to `database/cat_assets_library.blend`.
    If the repository was cloned with split chunks (`cat_assets_library.blend.part01` + `.part02`)
    and `cat_assets_library.blend` has not been assembled yet, automatically reassembles it!
    """
    db_dir = get_database_dir()
    lib_path = os.path.join(db_dir, "cat_assets_library.blend")
    if os.path.isfile(lib_path) and os.path.getsize(lib_path) > 10_000_000:
        return lib_path

    parts = sorted(glob.glob(os.path.join(db_dir, "cat_assets_library.blend.part*")))
    if parts:
        tmp_path = os.path.join(db_dir, "cat_assets_library.blend.assembling")
        try:
            with open(tmp_path, "wb") as out_f:
                for p in parts:
                    with open(p, "rb") as in_f:
                        shutil.copyfileobj(in_f, out_f, length=8 * 1024 * 1024)
            os.replace(tmp_path, lib_path)
            print(f"[BlackCatStudio] Reassembled {lib_path} from {len(parts)} chunks.")
        except Exception as e:
            print(f"[BlackCatStudio] Warning assembling library chunks: {e}")

    return lib_path


def get_registry_json_path() -> str:
    return os.path.join(get_database_dir(), "registry.json")


def get_dropin_anims_dir() -> str:
    path = os.path.join(get_database_dir(), "animations_dropin")
    os.makedirs(path, exist_ok=True)
    return path


# ============================================================================
# 2. COLLECTIONS & TEMPLATE ROSTER
# ============================================================================

TEMPLATE_COLLECTION_NAME = "00_RIGGED_CAT_TEMPLATES"
ACTORS_COLLECTION_NAME = "01_CAT_ACTORS"
PATHS_COLLECTION_NAME = "02_CAT_LOCOMOTION_CURVES"

CAT_TEMPLATE_ROOT_NAME = "Black Cat Animated"
CAT_TEMPLATE_ARMATURE_NAME = "cat"
CAT_TEMPLATE_BODY_MESH_NAME = "feline "
CAT_TEMPLATE_FUR_MESH_NAME = "BaseColor_white mail lion_lion 9(making mail hair )_new hai.063"
CAT_FUR_MODIFIER_NAME = "PS_Cat_FurCoat"

DEFAULT_WALK_ACTION = "Cat_Walk (1_32)"
DEFAULT_IDLE_ACTION = "Cat Idle seated (1_144)"
DEFAULT_JUMP_ACTION = "Cat _Jump  (1_27)"
DEFAULT_SIT_ACTION = "Cat sitting (1-24)"
DEFAULT_PAW_LICK_ACTION = "Cat_Seated_Paw_Lick (1_104)"
DEFAULT_PAW_REACH_ACTION = "Cat_Seated_Paw_Reach (1_72)"
DEFAULT_LOOK_AROUND_ACTION = "Cat_Seated_Look_Around (1_120)"

STRAY_BIOMECH_TRACK_NAME = "CAT_Stray_Biomechanics"

EYELID_CLOSED_LOCATIONS = {
    "lid.B.L.002": (-0.001222, 0.008306, -0.001019),
    "lid.B.L.003": (0.002773, 0.002497, 0.001881),
    "lid.B.R.002": (0.001222, 0.008306, -0.001019),
    "lid.B.R.003": (-0.002773, 0.002497, 0.001881),
    "lid.T.L.002": (0.005831, -0.013359, 0.006670),
    "lid.T.L.003": (0.000222, -0.000483, 0.002317),
    "lid.T.R.002": (-0.005831, -0.013359, 0.006670),
    "lid.T.R.003": (-0.000222, -0.000483, 0.002317),
}

# Optional action alias table for custom user action names
LEGACY_ACTION_ALIASES = {}

# Calibrated stride lengths and locomotion speeds (m/s at scale = 1.0, 24 FPS)
# At scale=1.0: `Cat_Walk (1_32)` (32f = 1.333s) has a 0.427m 4-beat stride -> 0.32 m/s
CAT_ACTION_CATALOG = {
    # --- LOCOMOTION (moves along 3D curve with zero foot-slip) ---
    "Cat_Walk (1_32)": {
        "category": "LOCOMOTION",
        "is_locomotion": True,
        "speed_mps": 0.32,
        "default_role": "FILL",
        "label": "Walk Cycle (Steady)",
    },
    "Cat_ slow Run (1_12)": {
        "category": "LOCOMOTION",
        "is_locomotion": True,
        "speed_mps": 0.78,
        "default_role": "FILL",
        "label": "Trot / Slow Run",
    },
    "Cat _Run (1_16)": {
        "category": "LOCOMOTION",
        "is_locomotion": True,
        "speed_mps": 1.35,
        "default_role": "FILL",
        "label": "Gallop / Fast Run",
    },
    "Cat _Jump  (1_27)": {
        "category": "LOCOMOTION",
        "is_locomotion": True,
        "speed_mps": 0.85,
        "default_role": "FIXED",
        "label": "Jump / Leap Arc",
    },
    # --- POSTURE TRANSITIONS (Stationary, 0.0 m/s) ---
    "Cat sitting (1-24)": {
        "category": "TRANSITION",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Sit Down (Stand -> Sit)",
    },
    "Cat Standing  (1-24)": {
        "category": "TRANSITION",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Stand Up (Sit -> Stand)",
    },
    "Cat sitting on belly (1_32)": {
        "category": "TRANSITION",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Lie Down on Belly",
    },
    "Cat Standing From belly( 1_32)": {
        "category": "TRANSITION",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Get Up from Belly",
    },
    "Cat stand up (1_168)": {
        "category": "TRANSITION",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Stretch & Stand Up",
    },
    # --- GROOMING & INTERACTION (Stationary, 0.0 m/s) ---
    "Cat_Seated_Paw_Lick (1_104)": {
        "category": "GROOMING",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Seated Paw Lick & Grooming",
    },
    "Cat_Seated_Paw_Reach (1_72)": {
        "category": "INTERACTION",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Seated Paw Reach / Tap",
    },
    "Cat_Seated_Look_Around (1_120)": {
        "category": "STATIONARY",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Seated Head Look Around",
    },
    # --- IDLE & NATURAL FELINE BEHAVIORS (Stationary, 0.0 m/s) ---
    "Cat idle (1_143)": {
        "category": "STATIONARY",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Standing Idle (Breathing & Tail Sway)",
    },
    "Cat Idle seated (1_144)": {
        "category": "STATIONARY",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Seated Idle (Calm Observation)",
    },
    "Cat licking (1-143)": {
        "category": "GROOMING",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Standing Fur Lick",
    },
    "Cat scratching (1-143)": {
        "category": "GROOMING",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Scratch Ear with Hind Leg",
    },
    "Cat yawning (1_168)": {
        "category": "STATIONARY",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Yawn & Stretch",
    },
    "Cat Meerkating (1_168)": {
        "category": "STATIONARY",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Stand on Hind Legs (Meerkat Pose)",
    },
    "Cat Angry (1_25)": {
        "category": "REACTION",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Arched Back / Hiss",
    },
    "cat meow FA (1_48)": {
        "category": "FACIAL",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Meow Vocalization",
    },
    "Cat drinking (1-99)": {
        "category": "STATIONARY",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Drink Water",
    },
    "Cat eating (1_143)": {
        "category": "STATIONARY",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Eat from Bowl",
    },
    # --- SLEEPING & RESTING ---
    "Cat seated on belly (1_125) ": {
        "category": "SLEEP",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Resting on Belly (Loaf)",
    },
    "Cat sleeping on belly (1_143)": {
        "category": "SLEEP",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Sleeping on Belly",
    },
    "Cat sleeping On side  (1_143)": {
        "category": "SLEEP",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Sleeping on Side",
    },
    "Cat sleeping On back (1_143)": {
        "category": "SLEEP",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Sleeping on Back",
    },
    "Cat Rolling in sleep (1_48) ": {
        "category": "SLEEP",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Roll Over in Sleep",
    },
    # --- FACIAL POSES ---
    "FP Feline eye closed ": {
        "category": "FACIAL",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Eyes Closed Pose",
    },
    "FP feline Idle face ": {
        "category": "FACIAL",
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": "Neutral Facial Pose",
    },
}

# General-purpose NLA sequence presets
PRESET_WALK_STOP_GROOM_WALK = [
    {"action": "Cat idle (1_143)", "repeat": 0.35, "speed": 1.0, "blend": 0, "mode": "FIXED"},
    {"action": "Cat_Walk (1_32)", "repeat": 1.0, "speed": 1.0, "blend": 6, "mode": "FILL"},
    {"action": "Cat sitting (1-24)", "repeat": 1.0, "speed": 1.0, "blend": 6, "mode": "FIXED"},
    {"action": "Cat_Seated_Paw_Lick (1_104)", "repeat": 1.0, "speed": 1.0, "blend": 8, "mode": "FIXED"},
    {"action": "Cat Standing  (1-24)", "repeat": 1.0, "speed": 1.0, "blend": 6, "mode": "FIXED"},
    {"action": "Cat_Walk (1_32)", "repeat": 1.0, "speed": 1.0, "blend": 6, "mode": "FILL"},
    {"action": "Cat sitting (1-24)", "repeat": 1.0, "speed": 1.0, "blend": 6, "mode": "FIXED"},
    {"action": "Cat Idle seated (1_144)", "repeat": 0.50, "speed": 1.0, "blend": 8, "mode": "FIXED"},
]

PRESET_WALK_JUMP_LEDGE = [
    {"action": "Cat idle (1_143)", "repeat": 0.35, "speed": 1.0, "blend": 0, "mode": "FIXED"},
    {"action": "Cat_Walk (1_32)", "repeat": 0.35, "speed": 1.0, "blend": 6, "mode": "FILL"},
    {"action": "Cat _Jump  (1_27)", "repeat": 1.0, "speed": 1.0, "blend": 4, "mode": "FIXED"},
    {"action": "Cat_Walk (1_32)", "repeat": 1.0, "speed": 1.0, "blend": 5, "mode": "FILL"},
    {"action": "Cat sitting (1-24)", "repeat": 1.0, "speed": 1.0, "blend": 6, "mode": "FIXED"},
    {"action": "Cat_Seated_Paw_Lick (1_104)", "repeat": 1.0, "speed": 1.0, "blend": 8, "mode": "FIXED"},
    {"action": "Cat_Seated_Look_Around (1_120)", "repeat": 1.0, "speed": 1.0, "blend": 8, "mode": "FIXED"},
]

PRESET_PURE_WALK_CURVE = [
    {"action": "Cat_Walk (1_32)", "repeat": 1.0, "speed": 1.0, "blend": 0, "mode": "FILL"},
]

PRESET_SEATED_GROOMING_IDLE = [
    {"action": "Cat Idle seated (1_144)", "repeat": 0.50, "speed": 1.0, "blend": 0, "mode": "FIXED"},
    {"action": "Cat_Seated_Paw_Lick (1_104)", "repeat": 1.0, "speed": 1.0, "blend": 8, "mode": "FIXED"},
    {"action": "Cat_Seated_Look_Around (1_120)", "repeat": 1.0, "speed": 1.0, "blend": 8, "mode": "FIXED"},
    {"action": "cat meow FA (1_48)", "repeat": 1.0, "speed": 1.0, "blend": 6, "mode": "FIXED"},
    {"action": "Cat Idle seated (1_144)", "repeat": 0.50, "speed": 1.0, "blend": 8, "mode": "FIXED"},
]

# Default preset 3D curve control points around world origin (0, 0, 0)
DEFAULT_S_CURVE_POINTS = [
    (-1.40, 1.20, 0.00),
    (-0.55, 0.55, 0.00),
    (0.45, -0.15, 0.00),
    (1.25, -0.95, 0.00),
    (0.35, -1.75, 0.00),
]

DEFAULT_LEDGE_JUMP_CURVE_POINTS = [
    (-1.20, 0.90, 0.00),
    (-0.65, 0.45, 0.00),
    (-0.20, 0.15, 0.35),
    (0.55, -0.35, 0.35),
    (1.25, -0.95, 0.35),
]

DEFAULT_CIRCLE_CURVE_POINTS = [
    (0.00, 1.20, 0.00),
    (1.20, 0.00, 0.00),
    (0.00, -1.20, 0.00),
    (-1.20, 0.00, 0.00),
]


# ============================================================================
# 3. BLENDER 4.x / 5.x F-CURVE & COLLECTION HELPERS
# ============================================================================

def resolve_action_name(action_name: str) -> str:
    """Resolves legacy action names to canonical general-purpose names."""
    if not action_name:
        return ""
    return LEGACY_ACTION_ALIASES.get(action_name, action_name)


def ensure_collection(col_name: str, parent_col=None):
    col = bpy.data.collections.get(col_name)
    if not col:
        col = bpy.data.collections.new(col_name)
    target_parent = parent_col or bpy.context.scene.collection
    if col.name not in target_parent.children:
        try:
            target_parent.children.link(col)
        except Exception:
            pass
    return col


def get_action_fcurves(action):
    """Compatible F-Curve accessor for both Blender 4.x (`action.fcurves`) and Blender 5.x layered actions."""
    if not action:
        return []
    if hasattr(action, "fcurves") and len( getattr(action, "fcurves", [])) > 0:
        return action.fcurves
    if hasattr(action, "layers"):
        for layer in action.layers:
            for strip in getattr(layer, "strips", []):
                if hasattr(strip, "channelbags"):
                    for bag in strip.channelbags:
                        if hasattr(bag, "fcurves"):
                            return bag.fcurves
    return getattr(action, "fcurves", [])


def bind_action_slot(anim_data, action):
    """Ensures Blender 5.x `action_slot` is bound on `anim_data` or NLA `strip`."""
    if not anim_data or not action:
        return
    if hasattr(action, "slots") and len(action.slots) > 0:
        try:
            if getattr(anim_data, "action_slot", None) is None:
                anim_data.action_slot = action.slots[0]
        except Exception:
            pass


def load_registry() -> dict:
    reg_path = get_registry_json_path()
    if os.path.exists(reg_path):
        try:
            with open(reg_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"studio_version": "2.0.0", "character_roster": {}, "animations": []}


def save_registry(data: dict):
    reg_path = get_registry_json_path()
    try:
        os.makedirs(os.path.dirname(reg_path), exist_ok=True)
        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[BlackCatStudio] Warning saving registry: {e}")
