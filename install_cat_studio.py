#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Black Cat Animation Director Studio v2.0 — One-Click Universal Installer
========================================================================
Cross-platform installer (macOS / Windows / Linux) for Humans and AI Agents.

What this script does automatically:
  1. Reassembles `database/cat_assets_library.blend` from Git chunks (`.part01` + `.part02`)
     or downloads it from GitHub Release `v2.0.0` if missing.
  2. Writes `black_cat_director/_studio_paths.json` pointing to this repository's `database/`
     directory so the add-on works from ANY `.blend` file anywhere on the machine.
  3. Builds `black_cat_director_addon.zip` (with `_studio_paths.json` included).
  4. Detects all installed Blender 4.x / 5.x versions (macOS, Windows, Linux), installs
     `black_cat_director` into Blender's `scripts/addons/black_cat_director`, and enables
     the add-on in Blender User Preferences.
  5. Generates a clean, general-purpose `black_cat_studio.blend` quickstart studio scene
     with `CTRL_Cat_01` (furless viewport for fast animation, 180,000-strand 3D fur in render),
     `Cat_Path_01` 3D Bezier S-curve, zero-slip NLA sequence, studio 3-point lighting,
     and the `Black Cat Studio` N-Panel active.

Usage:
  python3 install_cat_studio.py
"""

import argparse
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_SLUG = "timon2200/black-cat-studio"
RELEASE_TAG = "v2.0.0"
RELEASE_BASE_URL = f"https://github.com/{REPO_SLUG}/releases/download/{RELEASE_TAG}"

STUDIO_ROOT = Path(__file__).resolve().parent
ADDON_SRC_DIR = STUDIO_ROOT / "black_cat_director"
DATABASE_DIR = STUDIO_ROOT / "database"
LIBRARY_BLEND = DATABASE_DIR / "cat_assets_library.blend"
ADDON_ZIP_PATH = STUDIO_ROOT / "black_cat_director_addon.zip"
STUDIO_BLEND = STUDIO_ROOT / "black_cat_studio.blend"


def log(msg: str):
    print(f"[BlackCatStudio Installer] {msg}", flush=True)


def ensure_library_blend() -> Path:
    """Reassembles `database/cat_assets_library.blend` from `.part01`+`.part02` or downloads from Release."""
    if LIBRARY_BLEND.is_file() and LIBRARY_BLEND.stat().st_size > 20_000_000:
        log(f"Found library database: {LIBRARY_BLEND.name} ({LIBRARY_BLEND.stat().st_size / (1024*1024):.1f} MB)")
        return LIBRARY_BLEND

    parts = sorted(DATABASE_DIR.glob("cat_assets_library.blend.part*"))
    if parts:
        log(f"Assembling {LIBRARY_BLEND.name} from {len(parts)} repository chunks...")
        tmp_path = DATABASE_DIR / "cat_assets_library.blend.assembling"
        with open(tmp_path, "wb") as out_f:
            for p in parts:
                with open(p, "rb") as in_f:
                    shutil.copyfileobj(in_f, out_f, length=8 * 1024 * 1024)
        tmp_path.replace(LIBRARY_BLEND)
        log(f"Assembled {LIBRARY_BLEND.name} ({LIBRARY_BLEND.stat().st_size / (1024*1024):.1f} MB)")
        return LIBRARY_BLEND

    url = f"{RELEASE_BASE_URL}/cat_assets_library.blend"
    log(f"Downloading {LIBRARY_BLEND.name} from {url} ...")
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, LIBRARY_BLEND)
    log(f"Downloaded {LIBRARY_BLEND.name} ({LIBRARY_BLEND.stat().st_size / (1024*1024):.1f} MB)")
    return LIBRARY_BLEND


def write_studio_paths_config() -> Path:
    """Writes `_studio_paths.json` inside `black_cat_director/` so the installed add-on finds `database/`."""
    cfg_path = ADDON_SRC_DIR / "_studio_paths.json"
    payload = {
        "studio_root": str(STUDIO_ROOT),
        "database_dir": str(DATABASE_DIR),
    }
    cfg_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Configured portable studio paths -> {cfg_path}")
    return cfg_path


def build_addon_zip() -> Path:
    """Builds `black_cat_director_addon.zip` ready for Blender Preferences -> Install from Disk."""
    with zipfile.ZipFile(ADDON_ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in sorted(ADDON_SRC_DIR.rglob("*")):
            if "__pycache__" in file_path.parts or file_path.suffix in (".pyc", ".pyo", ".DS_Store"):
                continue
            if file_path.is_file():
                arcname = Path("black_cat_director") / file_path.relative_to(ADDON_SRC_DIR)
                zf.write(file_path, arcname.as_posix())
    log(f"Built Blender Add-on archive -> {ADDON_ZIP_PATH.name} ({ADDON_ZIP_PATH.stat().st_size / 1024:.1f} KB)")
    return ADDON_ZIP_PATH


def find_blender_user_addons_dirs() -> list:
    """Finds Blender 4.x / 5.x user add-on directories across macOS, Windows, and Linux."""
    system = platform.system()
    home = Path.home()
    base_dirs = []
    if system == "Darwin":
        base_dirs.append(home / "Library" / "Application Support" / "Blender")
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            base_dirs.append(Path(appdata) / "Blender Foundation" / "Blender")
    else:
        base_dirs.append(home / ".config" / "blender")

    addon_dirs = []
    for base in base_dirs:
        if not base.is_dir():
            continue
        for ver_dir in sorted(base.iterdir()):
            if ver_dir.is_dir() and re.match(r"^[45]\.\d+$", ver_dir.name):
                ad = ver_dir / "scripts" / "addons"
                ad.mkdir(parents=True, exist_ok=True)
                addon_dirs.append(ad)
    return addon_dirs


def install_into_blender_addons() -> list:
    installed = []
    for addon_dir in find_blender_user_addons_dirs():
        dest = addon_dir / "black_cat_director"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(
            ADDON_SRC_DIR,
            dest,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
        )
        installed.append(dest)
        log(f"Installed add-on into -> {dest}")
    return installed


def find_blender_executable() -> str:
    env_bin = os.environ.get("BLENDER_BIN", "").strip()
    if env_bin and os.path.isfile(env_bin):
        return env_bin

    which_bin = shutil.which("blender") or shutil.which("Blender")
    if which_bin:
        return which_bin

    system = platform.system()
    if system == "Darwin":
        for p in (
            "/Applications/Blender.app/Contents/MacOS/Blender",
            str(Path.home() / "Applications/Blender.app/Contents/MacOS/Blender"),
        ):
            if os.path.isfile(p):
                return p
    elif system == "Windows":
        prog = os.environ.get("ProgramFiles", r"C:\Program Files")
        matches = sorted(glob.glob(os.path.join(prog, "Blender Foundation", "Blender*", "blender.exe")), reverse=True)
        if matches:
            return matches[0]
    return ""


def enable_addon_and_build_studio_blend(blender_bin: str, build_scene: bool = True):
    if not blender_bin:
        log("Blender executable not found in standard paths; add-on files and .zip are ready.")
        return

    log(f"Using Blender executable: {blender_bin}")
    py_code = f"""
import os, sys, bpy

studio_root = {repr(str(STUDIO_ROOT))}
if studio_root not in sys.path:
    sys.path.insert(0, studio_root)

try:
    bpy.ops.preferences.addon_enable(module="black_cat_director")
    bpy.ops.wm.save_userpref()
    print("[BlackCatStudio] Enabled black_cat_director in Blender User Preferences.")
except Exception as e:
    print("[BlackCatStudio] Preferences note:", e)

if {repr(bool(build_scene))}:
    # Clear default startup cube/light
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    import black_cat_director as cd
    cd.reload_all_submodules()
    res = cd.integrate_cat_studio(
        spawn_demo=True,
        preset="WALK_GROOM_WALK",
        viewport_fur=False,
        render_fur=True,
    )

    # Create clean studio floor & 3-point lighting + camera
    bpy.ops.mesh.primitive_plane_add(size=8.0, location=(0.0, -0.25, 0.0))
    floor = bpy.context.active_object
    floor.name = "Studio_Ground_Floor"
    mat_fl = bpy.data.materials.new("Studio_Floor_Mat")
    mat_fl.use_nodes = True
    bsdf_f = next((n for n in mat_fl.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if bsdf_f:
        bsdf_f.inputs["Base Color"].default_value = (0.14, 0.15, 0.17, 1.0)
        bsdf_f.inputs["Roughness"].default_value = 0.75
    floor.data.materials.append(mat_fl)

    # Key, Rim, and Fill lights optimized for 3D feline fur strands
    key_data = bpy.data.lights.new("LGT_Studio_Key", type="AREA")
    key_data.energy = 120.0
    key_data.size = 1.8
    key_data.color = (1.0, 0.96, 0.90)
    key_obj = bpy.data.objects.new("LGT_Studio_Key", key_data)
    key_obj.location = (1.8, -2.2, 2.1)
    key_obj.rotation_euler = (0.78, 0.0, 0.62)
    bpy.context.scene.collection.objects.link(key_obj)

    rim_data = bpy.data.lights.new("LGT_Studio_FurRim", type="AREA")
    rim_data.energy = 95.0
    rim_data.size = 1.5
    rim_data.color = (0.82, 0.90, 1.0)
    rim_data.diffuse_factor = 1.35
    rim_data.specular_factor = 0.75
    rim_obj = bpy.data.objects.new("LGT_Studio_FurRim", rim_data)
    rim_obj.location = (-1.6, 1.9, 1.6)
    rim_obj.rotation_euler = (-0.85, 0.0, -0.68)
    bpy.context.scene.collection.objects.link(rim_obj)

    cam_data = bpy.data.cameras.new("CAM_Cat_Studio")
    cam_data.lens = 50.0
    cam_obj = bpy.data.objects.new("CAM_Cat_Studio", cam_data)
    cam_obj.location = (1.95, -2.35, 0.88)
    cam_obj.rotation_euler = (1.32, 0.0, 0.68)
    bpy.context.scene.collection.objects.link(cam_obj)
    bpy.context.scene.camera = cam_obj

    # Embed bootstrap_cat_studio.py so opening the .blend auto-registers the N-panel
    boot_path = os.path.join(studio_root, "bootstrap_cat_studio.py")
    if os.path.isfile(boot_path):
        txt = bpy.data.texts.get("bootstrap_cat_studio.py") or bpy.data.texts.new("bootstrap_cat_studio.py")
        with open(boot_path, "r", encoding="utf-8") as f:
            txt.from_string(f.read())
        txt.use_module = True

    ctrl = bpy.data.objects.get("CTRL_Cat_01")
    if ctrl:
        for o in bpy.context.selected_objects:
            o.select_set(False)
        ctrl.select_set(True)
        bpy.context.view_layer.objects.active = ctrl

    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath={repr(str(STUDIO_BLEND))}, compress=True)
    print("[BlackCatStudio] Saved studio scene ->", {repr(str(STUDIO_BLEND))})
"""
    subprocess.run([blender_bin, "-b", "--factory-startup", "--python-expr", py_code], check=True)


def main():
    parser = argparse.ArgumentParser(description="Install Black Cat Animation Director Studio v2.0")
    parser.add_argument("--no-scene", action="store_true", help="Skip generating black_cat_studio.blend")
    args = parser.parse_args()

    ensure_library_blend()
    write_studio_paths_config()
    build_addon_zip()
    install_into_blender_addons()
    blender_bin = find_blender_executable()
    enable_addon_and_build_studio_blend(blender_bin, build_scene=not args.no_scene)
    log("Installation complete! Open Blender -> View3D Sidebar (N) -> 'Black Cat Studio'.")


if __name__ == "__main__":
    main()
