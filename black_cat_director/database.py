# -*- coding: utf-8 -*-
"""
Black Cat Animation Director Studio v2.0 — Asset Database & Action Manager
==========================================================================
Manages automatic lazy-loading of the rigged Black Cat template (`00_RIGGED_CAT_TEMPLATES`),
its 180,000-strand 3D Feline Fur Coat (`PS_Cat_FurCoat`), and all 29 quadruped
animations from `database/cat_assets_library.blend`.
"""

import glob
import os
import bpy

from .constants import (
    CAT_ACTION_CATALOG,
    CAT_TEMPLATE_ARMATURE_NAME,
    CAT_TEMPLATE_BODY_MESH_NAME,
    CAT_TEMPLATE_FUR_MESH_NAME,
    CAT_TEMPLATE_ROOT_NAME,
    TEMPLATE_COLLECTION_NAME,
    ensure_collection,
    get_action_fcurves,
    get_dropin_anims_dir,
    get_library_blend_path,
    load_registry,
    resolve_action_name,
    save_registry,
)


def _restore_action_metadata():
    """Restores custom properties (`cat_category`, `cat_is_locomotion`, `cat_speed_mps`, `cat_role`, `cat_label`) on loaded Actions."""
    reg_data = load_registry()
    reg_map = {
        a["name"]: a
        for a in reg_data.get("animations", [])
        if isinstance(a, dict) and "name" in a
    }

    for act in bpy.data.actions:
        if act.name.startswith("PathAnim_"):
            continue
        meta = CAT_ACTION_CATALOG.get(act.name) or reg_map.get(act.name)
        if meta:
            act.use_fake_user = True
            act["cat_category"] = meta.get("category", "STATIONARY")
            act["cat_is_locomotion"] = bool(meta.get("is_locomotion", False))
            act["cat_speed_mps"] = float(meta.get("speed_mps", 0.0))
            act["cat_role"] = meta.get("default_role", "FIXED")
            act["cat_label"] = meta.get("label", act.name)


def ensure_cat_database_loaded() -> bool:
    """
    Ensures the rigged Black Cat template (`00_RIGGED_CAT_TEMPLATES`) and all
    quadruped animations are loaded into the current `.blend` file from
    `database/cat_assets_library.blend`, and configures 3D strip hair rendering.
    """
    try:
        scn = getattr(bpy.context, "scene", None)
        if scn and hasattr(scn, "render"):
            scn.render.hair_type = "STRIP"
            scn.render.hair_subdiv = 1
    except Exception:
        pass

    has_template = (
        bpy.data.objects.get(CAT_TEMPLATE_ARMATURE_NAME) is not None
        and bpy.data.objects.get(CAT_TEMPLATE_BODY_MESH_NAME) is not None
    )
    existing_cat_actions = [a for a in bpy.data.actions if a.name in CAT_ACTION_CATALOG]

    if has_template and len(existing_cat_actions) >= 15:
        _restore_action_metadata()
        return True

    lib_path = get_library_blend_path()
    if not os.path.exists(lib_path):
        print(f"[BlackCatStudio] Library not found at: {lib_path}")
        return False

    try:
        with bpy.data.libraries.load(lib_path, link=False) as (data_from, data_to):
            if not has_template:
                if TEMPLATE_COLLECTION_NAME in data_from.collections:
                    data_to.collections = [TEMPLATE_COLLECTION_NAME]
                elif "Black Cat Animated" in data_from.collections:
                    data_to.collections = ["Black Cat Animated"]
                else:
                    wanted_objs = [
                        n for n in (
                            CAT_TEMPLATE_ROOT_NAME,
                            CAT_TEMPLATE_ARMATURE_NAME,
                            CAT_TEMPLATE_BODY_MESH_NAME,
                            CAT_TEMPLATE_FUR_MESH_NAME,
                        )
                        if n in data_from.objects
                    ]
                    data_to.objects = wanted_objs

            missing_actions = [
                a_name for a_name in data_from.actions
                if a_name not in bpy.data.actions and not a_name.startswith("PathAnim_")
            ]
            data_to.actions = missing_actions
    except Exception as e:
        print(f"[BlackCatStudio] Error loading {lib_path}: {e}")
        return False

    tpl_col = ensure_collection(TEMPLATE_COLLECTION_NAME)
    tpl_col.hide_viewport = True
    tpl_col.hide_render = True

    for o_name in (
        CAT_TEMPLATE_ROOT_NAME,
        CAT_TEMPLATE_ARMATURE_NAME,
        CAT_TEMPLATE_BODY_MESH_NAME,
        CAT_TEMPLATE_FUR_MESH_NAME,
    ):
        obj = bpy.data.objects.get(o_name)
        if obj and obj.name not in tpl_col.objects:
            try:
                tpl_col.objects.link(obj)
            except Exception:
                pass
        if obj:
            obj.hide_viewport = True
            obj.hide_render = True

    try:
        vl_col = bpy.context.view_layer.layer_collection.children.get(TEMPLATE_COLLECTION_NAME)
        if vl_col:
            vl_col.exclude = True
    except Exception:
        pass

    _restore_action_metadata()
    return True


def set_action_cyclic_loop(action, enabled: bool = True) -> bool:
    """Enables or removes `CYCLES` F-Curve modifiers on `action`."""
    if not action:
        return False
    fcs = get_action_fcurves(action)
    for fc in fcs:
        for mod in list(fc.modifiers):
            if mod.type == "CYCLES":
                fc.modifiers.remove(mod)
        if enabled:
            fc.modifiers.new(type="CYCLES")
    return True


def zero_out_cat_root_translation(action) -> bool:
    """
    Zeros horizontal root/torso XY forward translation inside a locomotion cycle
    if an imported clip contains non-in-place root motion, so curve locomotion
    never double-translates the cat.
    """
    if not action:
        return False
    fcs = get_action_fcurves(action)
    modified = False
    for fc in fcs:
        dp = getattr(fc, "data_path", "")
        if 'pose.bones["root"]' in dp and dp.endswith("location") and fc.array_index in (0, 1):
            for kp in fc.keyframe_points:
                kp.co[1] = 0.0
                kp.handle_left[1] = 0.0
                kp.handle_right[1] = 0.0
            fc.update()
            modified = True
    return modified


def scan_and_import_dropin_cat_animations(context=None) -> list:
    """
    Scans `database/animations_dropin/` for `.fbx` / `.blend` files and imports
    any new quadruped Actions into the active scene and registry.
    """
    dropin_dir = get_dropin_anims_dir()
    imported = []

    blend_files = sorted(glob.glob(os.path.join(dropin_dir, "*.blend")))
    for bf in blend_files:
        try:
            with bpy.data.libraries.load(bf, link=False) as (data_from, data_to):
                new_acts = [a for a in data_from.actions if a not in bpy.data.actions]
                data_to.actions = new_acts
            for act in data_to.actions:
                if act:
                    act.use_fake_user = True
                    act["cat_category"] = "CUSTOM"
                    act["cat_is_locomotion"] = ("walk" in act.name.lower() or "run" in act.name.lower())
                    act["cat_speed_mps"] = 0.32 if act["cat_is_locomotion"] else 0.0
                    act["cat_role"] = "FILL" if act["cat_is_locomotion"] else "FIXED"
                    act["cat_label"] = act.name
                    imported.append(act.name)
        except Exception as e:
            print(f"[BlackCatStudio] Warning scanning {bf}: {e}")

    if imported:
        _restore_action_metadata()
    return imported


def list_available_cat_actions() -> list:
    """Returns sorted list of all available Cat Actions with metadata."""
    ensure_cat_database_loaded()
    result = []
    priority_order = list(CAT_ACTION_CATALOG.keys())

    for a_name in priority_order:
        act = bpy.data.actions.get(a_name)
        if act:
            meta = CAT_ACTION_CATALOG[a_name]
            span = int(round(act.frame_range[1] - act.frame_range[0]))
            result.append({
                "name": act.name,
                "label": meta.get("label", act.name),
                "category": meta.get("category", "STATIONARY"),
                "is_locomotion": bool(meta.get("is_locomotion", False)),
                "speed_mps": float(meta.get("speed_mps", 0.0)),
                "default_role": meta.get("default_role", "FIXED"),
                "frames": span,
            })

    for act in sorted(bpy.data.actions, key=lambda x: x.name):
        if act.name in CAT_ACTION_CATALOG or act.name.startswith("PathAnim_"):
            continue
        if any(act.name.startswith(p) for p in ("Cat", "cat", "feline", "FP ", "P ")):
            span = int(round(act.frame_range[1] - act.frame_range[0]))
            result.append({
                "name": act.name,
                "label": act.get("cat_label", act.name),
                "category": act.get("cat_category", "CUSTOM"),
                "is_locomotion": bool(act.get("cat_is_locomotion", False)),
                "speed_mps": float(act.get("cat_speed_mps", 0.0)),
                "default_role": act.get("cat_role", "FIXED"),
                "frames": span,
            })

    return result
