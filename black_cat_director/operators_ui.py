# -*- coding: utf-8 -*-
"""
Black Cat Animation Director Studio v2.0 — Operators, N-Panel UI & Viewport Handlers
====================================================================================
Provides the `Black Cat Studio` N-Panel (`VIEW3D_PT_black_cat_director_studio`) in the
3D Viewport Sidebar (`N` > `Black Cat Studio`) with:
  - 1-Click Actor Spawning (`CTRL_Cat_01`) with Furless Viewport by default (`show_viewport=False`)
    and 180,000-strand 3D Fur Coat in Render (`show_render=True`),
  - Live Fur Controls (Viewport Fur Toggle, Render Fur Toggle, Fur Length & Density),
  - Interactive 3D Curve Drawing (`Draw Curve Path` + `Finish Drawing & Follow Curve`)
    and Zero-Slip Curve Locomotion (`0.00 mm` foot sliding on walking/running clips),
  - Full NLA Animation Stacker & Strip Inspector + 1-Click Blender NLA Editor Sync,
  - Stray-Style Procedural Quadruped Biomechanics (Spine S-Bend, Tail Rudder, Blinks) &
    Additive Pose Offset Sliders.
"""

import json
import math
import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel

from .constants import (
    CAT_ACTION_CATALOG,
    DEFAULT_IDLE_ACTION,
    DEFAULT_WALK_ACTION,
    PATHS_COLLECTION_NAME,
    PRESET_PURE_WALK_CURVE,
    PRESET_SEATED_GROOMING_IDLE,
    PRESET_WALK_JUMP_LEDGE,
    PRESET_WALK_STOP_GROOM_WALK,
    ensure_collection,
    resolve_action_name,
)
from .database import (
    ensure_cat_database_loaded,
    list_available_cat_actions,
    scan_and_import_dropin_cat_animations,
)
from .locomotion import (
    attach_cat_to_locomotion_curve,
    bake_stray_biomechanics_layer,
    compute_curve_true_1d_length,
    create_cat_walk_curve,
    detach_cat_from_curve,
    get_cat_exact_stride_speed,
    sample_curve_arclength_table_3d,
)
from .nla_sequencer import (
     adjust_cat_nla_clip_repeat,
    append_cat_animation_to_nla,
    apply_cat_additive_pose_offset,
    assign_cat_action_with_slot,
    clear_cat_additive_pose_offset,
    clear_cat_nla_sequence,
    duplicate_cat_nla_clip,
    get_cat_nla_sequence_clips,
    move_cat_nla_clip,
    rebuild_cat_nla_sequence_from_specs,
    remove_cat_nla_clip_at_index,
    set_cat_head_look_at_target,
    sync_manual_nla_edits_to_specs,
    toggle_cat_nla_clip_fill_mode,
    update_cat_nla_clip_properties,
)
from .rig_actors import (
    configure_cat_fur_coat,
    configure_cat_look,
    find_cat_armature,
    find_cat_controller,
    find_cat_meshes,
    is_cat_controller,
    spawn_cat_actor,
)


# ============================================================================
# 1. DYNAMIC ENUM & PROPERTY CALLBACKS
# ============================================================================

_SYNCING_UI = False
_ACTION_ENUM_CACHE = []


def _get_action_enum_items(self, context):
    global _ACTION_ENUM_CACHE
    items = []
    for a_name, meta in CAT_ACTION_CATALOG.items():
        act = bpy.data.actions.get(a_name)
        if act:
            span = int(round(act.frame_range[1] - act.frame_range[0]))
            cat_tag = meta.get("category", "ANIM")[:4]
            spd = meta.get("speed_mps", 0.0)
            spd_str = f" [{spd:.2f} m/s]" if spd > 0.01 else ""
            lbl = f"[{cat_tag}] {meta.get('label', a_name)} ({span}f){spd_str}"
            items.append((act.name, lbl, f"{act.name} ({span} frames)"))

    for act in sorted(bpy.data.actions, key=lambda x: x.name):
        if act.name in CAT_ACTION_CATALOG or act.name.startswith("PathAnim_") or act.name.startswith("CAT_"):
            continue
        if any(act.name.startswith(p) for p in ("Cat", "cat", "feline", "FP ", "P ")):
            span = int(round(act.frame_range[1] - act.frame_range[0]))
            items.append((act.name, f"[CUST] {act.name} ({span}f)", act.name))

    if not items:
        items.append(("NONE", "Load Database First", "Click Load Cat Database"))
    _ACTION_ENUM_CACHE = items
    return _ACTION_ENUM_CACHE


def _poll_curve_object(self, obj):
    return obj is not None and obj.type == "CURVE"


def _on_cat_transform_or_anim_Changed(self, context):
    if _SYNCING_UI:
        return
    ctrl = find_cat_controller(context.active_object)
    if not ctrl:
        return

    s = max(0.1, float(context.scene.cat_dir_char_scale))
    ctrl.scale = (s, s, s)
    ctrl["cat_char_scale"] = s
    ctrl["cat_anim_speed"] = float(context.scene.cat_dir_anim_speed)
    ctrl["cat_frame_offset"] = int(context.scene.cat_dir_frame_offset)
    ctrl["cat_loop_anim"] = bool(context.scene.cat_dir_loop_anim)
    ctrl["cat_curve_start_pct"] = float(context.scene.cat_dir_curve_start_pct)
    ctrl["cat_flip_curve_dir"] = bool(context.scene.cat_dir_flip_curve)

    configure_cat_look(ctrl, look_mode=context.scene.cat_dir_look_mode)

    clips = get_cat_nla_sequence_clips(ctrl)
    if clips:
        raw_json = ctrl.get("cat_nla_sequence_json", "")
        if raw_json:
            try:
                specs = json.loads(raw_json)
                rebuild_cat_nla_sequence_from_specs(ctrl, specs, sync_curve=True)
            except Exception:
                pass
    else:
        arm = find_cat_armature(ctrl)
        act_name = ctrl.get("cat_anim_name", DEFAULT_IDLE_ACTION)
        act = bpy.data.actions.get(act_name)
        if arm and act:
            assign_cat_action_with_slot(
                arm,
                act,
                speed_mult=ctrl["cat_anim_speed"],
                frame_offset=ctrl["cat_frame_offset"],
                loop_enabled=ctrl["cat_loop_anim"],
            )
        cname = ctrl.get("cat_attached_curve", "")
        cobj = bpy.data.objects.get(cname) if cname else None
        if cobj and cobj.type == "CURVE":
            attach_cat_to_locomotion_curve(
                context,
                ctrl_obj=ctrl,
                curve_obj=cobj,
                loop_path=ctrl["cat_loop_anim"],
                flip_forward=ctrl["cat_flip_curve_dir"],
                start_pct=ctrl["cat_curve_start_pct"],
            )


def _on_cat_fur_props_changed(self, context):
    if _SYNCING_UI:
        return
    ctrl = find_cat_controller(context.active_object)
    if not ctrl:
        return
    configure_cat_fur_coat(
        ctrl,
        viewport_fur=bool(context.scene.cat_dir_fur_viewport),
        render_fur=bool(context.scene.cat_dir_fur_render),
        fur_length_m=float(context.scene.cat_dir_fur_length_mm) * 0.001,
        fur_children=int(context.scene.cat_dir_fur_children),
    )


def _on_cat_pose_offset_changed(self, context):
    if _SYNCING_UI:
        return
    ctrl = find_cat_controller(context.active_object)
    if not ctrl:
        return
    scn = context.scene
    apply_cat_additive_pose_offset(
        ctrl,
        head_yaw_deg=scn.cat_dir_pose_head_yaw,
        head_pitch_deg=scn.cat_dir_pose_head_pitch,
        spine_arch_deg=scn.cat_dir_pose_spine_arch,
        tail_pitch_deg=scn.cat_dir_pose_tail_pitch,
        tail_wag_deg=scn.cat_dir_pose_tail_wag,
    )
    set_cat_head_look_at_target(
        ctrl,
        target_obj=scn.cat_dir_look_target_obj,
        weight=scn.cat_dir_look_at_weight,
    )


def _on_active_strip_props_changed(self, context):
    if _SYNCING_UI:
        return
    ctrl = find_cat_controller(context.active_object)
    if not ctrl:
        return
    scn = context.scene
    idx = int(scn.cat_dir_active_strip_idx)
    update_cat_nla_clip_properties(
        ctrl,
        index=idx,
        action_name=scn.cat_dir_strip_action_enum if scn.cat_dir_strip_action_enum != "NONE" else None,
        repeat=float(scn.cat_dir_strip_repeat),
        speed=float(scn.cat_dir_strip_speed),
        blend=int(scn.cat_dir_strip_blend),
        mode=str(scn.cat_dir_strip_mode),
    )


def sync_ui_from_active_cat(ctrl_obj, scene=None):
    global _SYNCING_UI
    if not ctrl_obj:
        return
    if scene is None:
        scene = getattr(bpy.context, "scene", None)
    if not scene:
        return

    _SYNCING_UI = True
    try:
        scene.cat_dir_char_scale = float(ctrl_obj.get("cat_char_scale", ctrl_obj.scale.x))
        scene.cat_dir_anim_speed = float(ctrl_obj.get("cat_anim_speed", 1.0))
        scene.cat_dir_frame_offset = int(ctrl_obj.get("cat_frame_offset", 0))
        scene.cat_dir_loop_anim = bool(ctrl_obj.get("cat_loop_anim", False))
        scene.cat_dir_curve_start_pct = float(ctrl_obj.get("cat_curve_start_pct", 0.0))
        scene.cat_dir_flip_curve = bool(ctrl_obj.get("cat_flip_curve_dir", False))
        scene.cat_dir_look_mode = str(ctrl_obj.get("cat_look_mode", "PURE_BLACK"))

        scene.cat_dir_fur_viewport = bool(ctrl_obj.get("cat_fur_viewport", False))
        scene.cat_dir_fur_render = bool(ctrl_obj.get("cat_fur_render", True))
        scene.cat_dir_fur_length_mm = float(ctrl_obj.get("cat_fur_length_m", 0.018)) * 1000.0
        scene.cat_dir_fur_children = int(ctrl_obj.get("cat_fur_children", 36))

        scene.cat_dir_pose_head_yaw = float(ctrl_obj.get("cat_pose_head_yaw", 0.0))
        scene.cat_dir_pose_head_pitch = float(ctrl_obj.get("cat_pose_head_pitch", 0.0))
        scene.cat_dir_pose_spine_arch = float(ctrl_obj.get("cat_pose_spine_arch", 0.0))
        scene.cat_dir_pose_tail_pitch = float(ctrl_obj.get("cat_pose_tail_pitch", 0.0))
        scene.cat_dir_pose_tail_wag = float(ctrl_obj.get("cat_pose_tail_wag", 0.0))
        scene.cat_dir_look_at_weight = float(ctrl_obj.get("cat_look_at_target_weight", 0.0))

        cname = ctrl_obj.get("cat_attached_curve", "")
        if cname and bpy.data.objects.get(cname):
            scene.cat_dir_target_curve = bpy.data.objects.get(cname)

        aname = resolve_action_name(ctrl_obj.get("cat_anim_name", ""))
        if aname and bpy.data.actions.get(aname):
            try:
                scene.cat_dir_action_enum = aname
            except Exception:
                pass

        clips = get_cat_nla_sequence_clips(ctrl_obj)
        idx = int(scene.cat_dir_active_strip_idx)
        if clips:
            idx = max(0, min(len(clips) - 1, idx))
            scene.cat_dir_active_strip_idx = idx
            c = clips[idx]
            try:
                scene.cat_dir_strip_action_enum = c["action_name"]
            except Exception:
                pass
            scene.cat_dir_strip_repeat = float(c["repeat"])
            scene.cat_dir_strip_speed = float(c.get("speed", 1.0))
            scene.cat_dir_strip_blend = int(round(c["blend_in"]))
            scene.cat_dir_strip_mode = "FILL" if c["is_fill"] else "FIXED"
    finally:
        _SYNCING_UI = False


# ============================================================================
# 2. VIEWPORT SELECTION REDIRECT HANDLER
# ============================================================================

_LAST_ACTIVE_CAT_NAME = ""


def _cat_selection_redirect_handler(scene, depsgraph=None):
    """
    When the user clicks the cat's mesh (`MESH_Cat_01_Body`) in Object Mode,
    automatically redirects selection to its ground-ring controller (`CTRL_Cat_01`)
    and syncs the N-Panel sliders.
    """
    global _LAST_ACTIVE_CAT_NAME
    try:
        ctx = bpy.context
        if not ctx or not ctx.view_layer:
            return
        act_obj = ctx.view_layer.objects.active
        if not act_obj or getattr(act_obj, "mode", "OBJECT") != "OBJECT":
            return

        if act_obj.type == "MESH" and act_obj.get("cat_ctrl_name"):
            ctrl = bpy.data.objects.get(act_obj["cat_ctrl_name"])
            if ctrl and not ctrl.hide_viewport:
                act_obj.select_set(False)
                ctrl.select_set(True)
                ctx.view_layer.objects.active = ctrl
                act_obj = ctrl

        if is_cat_controller(act_obj) and act_obj.name != _LAST_ACTIVE_CAT_NAME:
            _LAST_ACTIVE_CAT_NAME = act_obj.name
            sync_ui_from_active_cat(act_obj, scene)
    except Exception:
        pass


# ============================================================================
# 3. OPERATORS — SPAWN, FUR COAT, CURVE DRAWING & NLA SEQUENCER
# ============================================================================

class CAT_OT_load_database(Operator):
    bl_idname = "cat_director.load_database"
    bl_label = "Load Cat Asset Library"
    bl_description = "Load rigged Black Cat template, 3D fur coat, and 29 quadruped animations from database/cat_assets_library.blend"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ok = ensure_cat_database_loaded()
        imported = scan_and_import_dropin_cat_animations(context)
        if ok:
            self.report({"INFO"}, f"Black Cat Library loaded ({len(bpy.data.actions)} actions, +{len(imported)} drop-in).")
            return {"FINISHED"}
        self.report({"ERROR"}, "Could not find database/cat_assets_library.blend!")
        return {"CANCELLED"}


class CAT_OT_spawn_cat(Operator):
    bl_idname = "cat_director.spawn_cat"
    bl_label = "+ Spawn Black Cat"
    bl_description = "Spawn a rigged Black Cat actor (furless in Viewport for fast animation, full 180,000-strand 3D fur in Render)"
    bl_options = {"REGISTER", "UNDO"}

    actor_name: StringProperty(name="Name", default="")

    def execute(self, context):
        ensure_cat_database_loaded()
        scn = context.scene

        if self.actor_name:
            target_name = self.actor_name
        else:
            idx = 1
            while bpy.data.objects.get(f"CTRL_Cat_{idx:02d}") is not None:
                idx += 1
            target_name = f"CTRL_Cat_{idx:02d}"

        cursor_loc = tuple(scn.cursor.location)
        if Vector_len := math.hypot(cursor_loc[0], cursor_loc[1]):
            loc = cursor_loc
        else:
            loc = (0.0, 0.0, 0.0)

        ctrl = spawn_cat_actor(
            name=target_name,
            location=loc,
            rotation_z_deg=0.0,
            scale=scn.cat_dir_char_scale,
            look_mode=scn.cat_dir_look_mode,
            initial_action=scn.cat_dir_action_enum if scn.cat_dir_action_enum != "NONE" else DEFAULT_IDLE_ACTION,
            viewport_fur=False,
            render_fur=True,
        )

        for o in context.selected_objects:
            o.select_set(False)
        ctrl.select_set(True)
        context.view_layer.objects.active = ctrl
        sync_ui_from_active_cat(ctrl, scn)

        self.report({"INFO"}, f"Spawned '{ctrl.name}' (Viewport Fur: OFF for fast animation, Render Fur: ON).")
        return {"FINISHED"}


class CAT_OT_toggle_viewport_fur(Operator):
    bl_idname = "cat_director.toggle_viewport_fur"
    bl_label = "Toggle Viewport 3D Fur"
    bl_description = "Keep Viewport Fur OFF for fast 60-165 FPS animation playback, or turn ON to preview 3D strands in Viewport"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            self.report({"WARNING"}, "Select a Black Cat actor first.")
            return {"CANCELLED"}
        cur = bool(ctrl.get("cat_fur_viewport", False))
        res = configure_cat_fur_coat(ctrl, viewport_fur=not cur)
        sync_ui_from_active_cat(ctrl, context.scene)
        state_str = "ON" if res.get("viewport_fur") else "OFF (Fast Animation Mode)"
        self.report({"INFO"}, f"Viewport 3D Fur: {state_str} (Render Fur: {'ON' if res.get('render_fur') else 'OFF'}).")
        return {"FINISHED"}


class CAT_OT_toggle_render_fur(Operator):
    bl_idname = "cat_director.toggle_render_fur"
    bl_label = "Toggle Render 3D Fur"
    bl_description = "Enable or disable the 180,000-strand 3D Feline Fur Coat in F12 / batch renders"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            self.report({"WARNING"}, "Select a Black Cat actor first.")
            return {"CANCELLED"}
        cur = bool(ctrl.get("cat_fur_render", True))
        res = configure_cat_fur_coat(ctrl, render_fur=not cur)
        sync_ui_from_active_cat(ctrl, context.scene)
        self.report({"INFO"}, f"Render 3D Fur: {'ON' if res.get('render_fur') else 'OFF'} ({res.get('total_strands', 180000):,} strands).")
        return {"FINISHED"}


class CAT_OT_apply_preset_sequence(Operator):
    bl_idname = "cat_director.apply_preset_sequence"
    bl_label = "Apply NLA Preset Sequence"
    bl_description = "Build a multi-clip NLA sequence preset with zero-slip curve locomotion and Stray biomechanics"
    bl_options = {"REGISTER", "UNDO"}

    preset_id: EnumProperty(
        name="Preset",
        items=[
            ("WALK_GROOM_WALK", "Walk -> Sit -> Lick Paw -> Walk (Zero-Slip)", "Walk along curve, pause to sit and lick paw, stand up and finish walking curve"),
            ("WALK_JUMP_LEDGE", "Walk -> Jump Ledge -> Sit -> Groom", "Walk to ledge, jump up, walk across ledge, sit and groom"),
            ("PURE_WALK", "Continuous Walk Along Curve (Zero-Slip)", "Pure stride-locked walk cycle along the entire curve"),
            ("SEATED_GROOM", "Seated Grooming, Look Around & Meow", "Stationary seated sequence with paw lick, head look around, and meow"),
        ],
        default="WALK_GROOM_WALK",
    )

    def execute(self, context):
        ensure_cat_database_loaded()
        scn = context.scene
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            ctrl = spawn_cat_actor(name="CTRL_Cat_01")

        curve_obj = scn.cat_dir_target_curve
        if self.preset_id == "WALK_JUMP_LEDGE":
            if not curve_obj:
                curve_obj = create_cat_walk_curve("Cat_Path_LedgeJump", preset_shape="LEDGE_JUMP")
                scn.cat_dir_target_curve = curve_obj
            ctrl["cat_attached_curve"] = curve_obj.name
            ok, msg = rebuild_cat_nla_sequence_from_specs(ctrl, PRESET_WALK_JUMP_LEDGE, sync_curve=True)
        elif self.preset_id == "WALK_GROOM_WALK":
            if not curve_obj:
                curve_obj = create_cat_walk_curve("Cat_Path_01", preset_shape="S_CURVE")
                scn.cat_dir_target_curve = curve_obj
            ctrl["cat_attached_curve"] = curve_obj.name
            ok, msg = rebuild_cat_nla_sequence_from_specs(ctrl, PRESET_WALK_STOP_GROOM_WALK, sync_curve=True)
        elif self.preset_id == "PURE_WALK":
            if not curve_obj:
                curve_obj = create_cat_walk_curve("Cat_Path_01", preset_shape="S_CURVE")
                scn.cat_dir_target_curve = curve_obj
            ctrl["cat_attached_curve"] = curve_obj.name
            ok, msg = rebuild_cat_nla_sequence_from_specs(ctrl, PRESET_PURE_WALK_CURVE, sync_curve=True)
        else:
            detach_cat_from_curve(context, ctrl)
            ok, msg = rebuild_cat_nla_sequence_from_specs(ctrl, PRESET_SEATED_GROOMING_IDLE, sync_curve=False)

        sync_ui_from_active_cat(ctrl, scn)
        self.report({"INFO" if ok else "WARNING"}, msg)
        return {"FINISHED"}


class CAT_OT_apply_single_action(Operator):
    bl_idname = "cat_director.apply_single_action"
    bl_label = "Apply Single Loop"
    bl_description = "Clear multi-clip NLA stack and loop the selected animation directly"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            self.report({"WARNING"}, "Select a Black Cat actor first.")
            return {"CANCELLED"}
        scn = context.scene
        act_name = scn.cat_dir_action_enum
        act = bpy.data.actions.get(act_name)
        if not act:
            self.report({"WARNING"}, f"Animation '{act_name}' not found.")
            return {"CANCELLED"}

        ctrl["cat_anim_name"] = act.name
        clear_cat_nla_sequence(ctrl)
        arm = find_cat_armature(ctrl)
        assign_cat_action_with_slot(
            arm,
            act,
            speed_mult=scn.cat_dir_anim_speed,
            frame_offset=scn.cat_dir_frame_offset,
            loop_enabled=scn.cat_dir_loop_anim,
        )

        cname = ctrl.get("cat_attached_curve", "")
        cobj = bpy.data.objects.get(cname) if cname else None
        if cobj and cobj.type == "CURVE":
            attach_cat_to_locomotion_curve(
                context,
                ctrl_obj=ctrl,
                curve_obj=cobj,
                loop_path=scn.cat_dir_loop_anim,
                flip_forward=scn.cat_dir_flip_curve,
                start_pct=scn.cat_dir_curve_start_pct,
            )

        self.report({"INFO"}, f"Applied '{act.name}' on '{ctrl.name}'.")
        return {"FINISHED"}


class CAT_OT_nla_add_clip(Operator):
    bl_idname = "cat_director.nla_add_clip"
    bl_label = "+ Add to NLA Stack"
    bl_description = "Append the selected animation to the NLA sequence stack (walking clips automatically follow the curve with zero foot-slip)"
    bl_options = {"REGISTER", "UNDO"}

    insert_at_playhead: BoolProperty(name="Insert at Playhead", default=False)
    default_mode: StringProperty(name="Mode", default="AUTO")

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            self.report({"WARNING"}, "Select a Black Cat actor first.")
            return {"CANCELLED"}
        scn = context.scene
        act_name = scn.cat_dir_action_enum
        act = bpy.data.actions.get(act_name)
        if not act:
            return {"CANCELLED"}

        if self.insert_at_playhead:
            cur_f = int(scn.frame_current)
            clips = get_cat_nla_sequence_clips(ctrl)
            raw_json = ctrl.get("cat_nla_sequence_json", "")
            specs = json.loads(raw_json) if raw_json else []
            if clips and specs:
                ins_idx = len(specs)
                for i, c in enumerate(clips):
                    if cur_f <= c["frame_end"]:
                        ins_idx = i + 1
                        break
                specs.insert(ins_idx, {
                    "action": act.name,
                    "repeat": 1.0,
                    "speed": float(scn.cat_dir_anim_speed),
                    "blend": int(scn.cat_dir_nla_blend_frames),
                    "mode": self.default_mode,
                })
                ok, msg = rebuild_cat_nla_sequence_from_specs(ctrl, specs, sync_curve=True)
                scn.cat_dir_active_strip_idx = min(ins_idx, len(specs) - 1)
                sync_ui_from_active_cat(ctrl, scn)
                self.report({"INFO" if ok else "WARNING"}, msg)
                return {"FINISHED"}

        ok, msg = append_cat_animation_to_nla(
            ctrl,
            action_name=act.name,
            repeat_count=1.0,
            blend_frames=scn.cat_dir_nla_blend_frames,
            speed_mult=scn.cat_dir_anim_speed,
            mode=self.default_mode,
        )
        clips = get_cat_nla_sequence_clips(ctrl)
        if clips:
            scn.cat_dir_active_strip_idx = len(clips) - 1
        sync_ui_from_active_cat(ctrl, scn)
        self.report({"INFO" if ok else "WARNING"}, msg)
        return {"FINISHED"}


class CAT_OT_nla_select_strip(Operator):
    bl_idname = "cat_director.nla_select_strip"
    bl_label = "Select NLA Strip"
    bl_description = "Select this NLA strip to inspect/edit its repeat count, playback speed, crossfade, and curve mode, and jump playhead to its start"
    bl_options = {"REGISTER", "UNDO"}

    clip_index: IntProperty(default=0)
    jump_playhead: BoolProperty(default=True)

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            return {"CANCELLED"}
        clips = get_cat_nla_sequence_clips(ctrl)
        if 0 <= self.clip_index < len(clips):
            context.scene.cat_dir_active_strip_idx = self.clip_index
            if self.jump_playhead:
                context.scene.frame_set(int(clips[self.clip_index]["frame_start"]))
            sync_ui_from_active_cat(ctrl, context.scene)
        return {"FINISHED"}


class CAT_OT_nla_edit_strip(Operator):
    bl_idname = "cat_director.nla_edit_strip"
    bl_label = "Edit NLA Strip"
    bl_description = "Reorder, duplicate, delete, adjust repeats, or toggle FILL/FIXED mode on an NLA strip"
    bl_options = {"REGISTER", "UNDO"}

    clip_index: IntProperty(default=0)
    operation: EnumProperty(
        items=[
            ("UP", "Move Up", ""),
            ("DOWN", "Move Down", ""),
            ("REMOVE", "Delete", ""),
            ("DUPLICATE", "Duplicate", ""),
            ("REP_PLUS", "+0.25x", ""),
            ("REP_MINUS", "-0.25x", ""),
            ("TOGGLE_FILL", "Toggle FILL/FIXED", ""),
        ],
        default="TOGGLE_FILL",
    )

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            return {"CANCELLED"}

        if self.operation == "UP":
            ok, msg = move_cat_nla_clip(ctrl, self.clip_index, -1)
            if ok:
                context.scene.cat_dir_active_strip_idx = max(0, self.clip_index - 1)
        elif self.operation == "DOWN":
            ok, msg = move_cat_nla_clip(ctrl, self.clip_index, 1)
            if ok:
                context.scene.cat_dir_active_strip_idx = self.clip_index + 1
        elif self.operation == "REMOVE":
            ok, msg = remove_cat_nla_clip_at_index(ctrl, self.clip_index)
        elif self.operation == "DUPLICATE":
            ok, msg = duplicate_cat_nla_clip(ctrl, self.clip_index)
            if ok:
                context.scene.cat_dir_active_strip_idx = self.clip_index + 1
        elif self.operation == "REP_PLUS":
            ok, msg = adjust_cat_nla_clip_repeat(ctrl, self.clip_index, +0.25)
        elif self.operation == "REP_MINUS":
            ok, msg = adjust_cat_nla_clip_repeat(ctrl, self.clip_index, -0.25)
        elif self.operation == "TOGGLE_FILL":
            ok, msg = toggle_cat_nla_clip_fill_mode(ctrl, self.clip_index)
        else:
            return {"CANCELLED"}

        sync_ui_from_active_cat(ctrl, context.scene)
        self.report({"INFO" if ok else "WARNING"}, msg)
        return {"FINISHED"}


class CAT_OT_nla_clear(Operator):
    bl_idname = "cat_director.nla_clear"
    bl_label = "Clear NLA Stack"
    bl_description = "Remove all NLA sequence tracks from the selected Black Cat actor"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            return {"CANCELLED"}
        clear_cat_nla_sequence(ctrl)
        self.report({"INFO"}, f"Cleared NLA stack on '{ctrl.name}'.")
        return {"FINISHED"}


class CAT_OT_open_nla_editor(Operator):
    bl_idname = "cat_director.open_nla_editor"
    bl_label = "Open Blender NLA Editor"
    bl_description = "Open or focus Blender's native NLA Editor with the cat's armature selected so you can view and drag strips directly"
    bl_options = {"REGISTER"}

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        arm = find_cat_armature(ctrl) if ctrl else None
        if arm:
            arm.hide_viewport = False
            arm.select_set(True)

        # Check if an NLA_EDITOR area is already visible; if not, convert TIMELINE or DOPESHEET_EDITOR to NLA_EDITOR
        nla_area = None
        fallback_area = None
        if context.screen:
            for area in context.screen.areas:
                if area.type == "NLA_EDITOR":
                    nla_area = area
                    break
                if area.type in ("DOPESHEET_EDITOR", "TIMELINE", "GRAPH_EDITOR"):
                    fallback_area = area

            if not nla_area and fallback_area:
                fallback_area.type = "NLA_EDITOR"
                nla_area = fallback_area

        self.report({"INFO"}, "NLA Editor ready. After manual edits in NLA Editor, click 'Sync Manual NLA Edits -> Curve'.")
        return {"FINISHED"}


class CAT_OT_nla_sync_manual(Operator):
    bl_idname = "cat_director.nla_sync_manual"
    bl_label = "Sync Manual NLA Edits -> Curve"
    bl_description = "Read manual strip changes from Blender's NLA Editor (repeats, scale, order, blend) and re-solve zero-slip curve locomotion"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            self.report({"WARNING"}, "Select a Black Cat actor first.")
            return {"CANCELLED"}
        ok, msg = sync_manual_nla_edits_to_specs(ctrl, sync_curve=True)
        sync_ui_from_active_cat(ctrl, context.scene)
        self.report({"INFO" if ok else "WARNING"}, msg)
        return {"FINISHED"}


class CAT_OT_draw_curve_path(Operator):
    bl_idname = "cat_director.draw_curve_path"
    bl_label = "1. Draw Curve Path (3D Surface)"
    bl_description = "Create a new 3D Bezier curve and activate Blender's interactive Curve Draw tool on surfaces. When done drawing, click '2. Finish Drawing & Follow Curve'"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scn = context.scene
        ctrl = find_cat_controller(context.active_object)
        if ctrl:
            scn["cat_last_active_ctrl"] = ctrl.name

        paths_col = ensure_collection(PATHS_COLLECTION_NAME)
        idx = 1
        while bpy.data.objects.get(f"Cat_Path_{idx:02d}") is not None:
            idx += 1
        cname = f"Cat_Path_{idx:02d}"

        cdata = bpy.data.curves.new(name=cname, type="CURVE")
        cdata.dimensions = "3D"
        cdata.resolution_u = 48
        cdata.bevel_depth = 0.008
        cobj = bpy.data.objects.new(cname, cdata)
        cobj.hide_render = True
        paths_col.objects.link(cobj)

        mat_name = "CAT_Curve_Path_Mat"
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf:
                bsdf.inputs["Base Color"].default_value = (0.15, 0.82, 1.0, 1.0)
        cdata.materials.append(mat)

        for o in context.selected_objects:
            o.select_set(False)
        cobj.select_set(True)
        context.view_layer.objects.active = cobj
        scn.cat_dir_target_curve = cobj

        try:
            bpy.ops.object.mode_set(mode="EDIT")
            cps = scn.tool_settings.curve_paint_settings
            cps.curve_type = "BEZIER"
            cps.depth_mode = "SURFACE"
            cps.surface_offset = 0.0
            cps.error_threshold = 8
            bpy.ops.wm.tool_set_by_id(name="builtin.draw")
        except Exception as e:
            print(f"[BlackCatStudio] Curve Draw tool notice: {e}")

        self.report({"INFO"}, f"Draw your path in the 3D Viewport on '{cname}', then click '2. Finish Drawing & Follow Curve'!")
        return {"FINISHED"}


class CAT_OT_finish_draw_and_bind(Operator):
    bl_idname = "cat_director.finish_draw_and_bind"
    bl_label = "2. Finish Drawing & Follow Curve (Zero-Slip)"
    bl_description = "Exit Curve Edit Mode, clean up the drawn curve, and bind the Black Cat actor to follow it with zero foot-slip"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scn = context.scene
        active_obj = context.active_object
        curve_obj = active_obj if (active_obj and active_obj.type == "CURVE") else scn.cat_dir_target_curve

        if active_obj and getattr(active_obj, "mode", "OBJECT") != "OBJECT":
            try:
                bpy.ops.object.mode_set(mode="OBJECT")
            except Exception:
                pass

        if not curve_obj or curve_obj.type != "CURVE":
            self.report({"WARNING"}, "No drawn 3D Curve found.")
            return {"CANCELLED"}

        # Remove any 0-point or 1-point stub splines if the user drew a fresh spline
        valid_splines = [
            sp for sp in curve_obj.data.splines
            if (len(sp.bezier_points) >= 2 if sp.type == "BEZIER" else len(sp.points) >= 2)
        ]
        if not valid_splines:
            # User clicked Finish without drawing a stroke -> populate a default S-curve so it still works cleanly
            create_cat_walk_curve(curve_obj.name, preset_shape="S_CURVE")
        elif len(valid_splines) < len(curve_obj.data.splines):
            for sp in list(curve_obj.data.splines):
                cnt = len(sp.bezier_points) if sp.type == "BEZIER" else len(sp.points)
                if cnt < 2:
                    curve_obj.data.splines.remove(sp)

        scn.cat_dir_target_curve = curve_obj
        ctrl = None
        last_name = scn.get("cat_last_active_ctrl", "")
        if last_name:
            ctrl = bpy.data.objects.get(last_name)
        if not ctrl:
            ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            ctrl = spawn_cat_actor(name="CTRL_Cat_01")

        # Ensure the cat has at least a Walk animation or NLA sequence when binding to a newly drawn curve
        clips = get_cat_nla_sequence_clips(ctrl)
        if not clips:
            rebuild_cat_nla_sequence_from_specs(ctrl, PRESET_PURE_WALK_CURVE, sync_curve=False)

        ok, msg = attach_cat_to_locomotion_curve(
            context,
            ctrl_obj=ctrl,
            curve_obj=curve_obj,
            loop_path=scn.cat_dir_loop_anim,
            flip_forward=scn.cat_dir_flip_curve,
            start_pct=scn.cat_dir_curve_start_pct,
        )

        for o in context.selected_objects:
            o.select_set(False)
        ctrl.select_set(True)
        context.view_layer.objects.active = ctrl
        sync_ui_from_active_cat(ctrl, scn)

        self.report({"INFO" if ok else "WARNING"}, msg)
        return {"FINISHED"}


class CAT_OT_create_preset_curve(Operator):
    bl_idname = "cat_director.create_preset_curve"
    bl_label = "Generate Preset Curve"
    bl_description = "Generate a ready-to-use 3D Bezier curve (S-Curve, Circle Loop, or Ledge Jump) and bind the cat"
    bl_options = {"REGISTER", "UNDO"}

    preset_shape: EnumProperty(
        name="Shape",
        items=[
            ("S_CURVE", "S-Curve Path", "Smooth S-curve on the ground (Z=0)"),
            ("CIRCLE", "Circle Loop Path", "Closed circular loop path"),
            ("LEDGE_JUMP", "Ledge Jump Path (Z+0.35m)", "Path with a 0.35m vertical ledge climb for Cat _Jump"),
        ],
        default="S_CURVE",
    )

    def execute(self, context):
        scn = context.scene
        name_map = {
            "S_CURVE": "Cat_Path_SCurve",
            "CIRCLE": "Cat_Path_Circle",
            "LEDGE_JUMP": "Cat_Path_LedgeJump",
        }
        cobj = create_cat_walk_curve(
            name=name_map.get(self.preset_shape, "Cat_Path_01"),
            preset_shape=self.preset_shape,
            cyclic=(self.preset_shape == "CIRCLE"),
        )
        scn.cat_dir_target_curve = cobj
        ctrl = find_cat_controller(context.active_object)
        if ctrl:
            clips = get_cat_nla_sequence_clips(ctrl)
            if not clips:
                rebuild_cat_nla_sequence_from_specs(ctrl, PRESET_PURE_WALK_CURVE, sync_curve=False)
            attach_cat_to_locomotion_curve(
                context,
                ctrl_obj=ctrl,
                curve_obj=cobj,
                loop_path=scn.cat_dir_loop_anim or (self.preset_shape == "CIRCLE"),
                flip_forward=scn.cat_dir_flip_curve,
                start_pct=scn.cat_dir_curve_start_pct,
            )
            sync_ui_from_active_cat(ctrl, scn)
        self.report({"INFO"}, f"Generated '{cobj.name}' ({compute_curve_true_1d_length(cobj):.2f} m).")
        return {"FINISHED"}


class CAT_OT_attach_to_curve(Operator):
    bl_idname = "cat_director.attach_to_curve"
    bl_label = "Bind / Sync Cat to Curve (Zero-Slip)"
    bl_description = "Bind the selected Black Cat actor to the target 3D curve and solve zero-slip locomotion keyframes"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        scn = context.scene
        ctrl = find_cat_controller(context.active_object)
        curve = scn.cat_dir_target_curve
        if not curve:
            for o in context.selected_objects:
                if o.type == "CURVE":
                    curve = o
                    break
        if not ctrl or not curve:
            self.report({"WARNING"}, "Select a Black Cat actor and pick or draw a 3D Curve.")
            return {"CANCELLED"}

        ok, msg = attach_cat_to_locomotion_curve(
            context,
            ctrl_obj=ctrl,
            curve_obj=curve,
            loop_path=scn.cat_dir_loop_anim,
            flip_forward=scn.cat_dir_flip_curve,
            start_pct=scn.cat_dir_curve_start_pct,
        )
        sync_ui_from_active_cat(ctrl, scn)
        self.report({"INFO" if ok else "WARNING"}, msg)
        return {"FINISHED"}


class CAT_OT_detach_from_curve(Operator):
    bl_idname = "cat_director.detach_from_curve"
    bl_label = "Detach from Curve"
    bl_description = "Detach the Black Cat actor from its curve while preserving its current world transform"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            return {"CANCELLED"}
        detach_cat_from_curve(context, ctrl)
        self.report({"INFO"}, f"Detached '{ctrl.name}' from curve.")
        return {"FINISHED"}


class CAT_OT_adjust_curve_point_tilt(Operator):
    bl_idname = "cat_director.adjust_curve_point_tilt"
    bl_label = "Adjust Curve Point Tilt (Yaw Offset)"
    bl_description = "Add yaw rotation offset (bp.tilt) to selected Bezier curve points and re-sync cat trajectory"
    bl_options = {"REGISTER", "UNDO"}

    delta_deg: FloatProperty(name="Delta Degrees", default=15.0)
    reset_zero: BoolProperty(name="Reset to 0°", default=False)

    def execute(self, context):
        scn = context.scene
        ctrl = find_cat_controller(context.active_object)
        curve = scn.cat_dir_target_curve
        if not curve and context.active_object and context.active_object.type == "CURVE":
            curve = context.active_object
        if not curve and ctrl:
            cname = ctrl.get("cat_attached_curve", "")
            if cname:
                curve = bpy.data.objects.get(cname)
        if not curve or curve.type != "CURVE" or not curve.data.splines:
            self.report({"WARNING"}, "No target 3D Curve found.")
            return {"CANCELLED"}

        sp = curve.data.splines[0]
        bpts = sp.bezier_points
        if not bpts:
            return {"CANCELLED"}

        selected_bpts = [bp for bp in bpts if bp.select_control_point]
        targets = selected_bpts if selected_bpts else [bpts[-1]]

        delta_rad = math.radians(float(self.delta_deg))
        for bp in targets:
            if self.reset_zero:
                bp.tilt = 0.0
            else:
                bp.tilt = float(bp.tilt) + delta_rad

        if ctrl and ctrl.get("cat_attached_curve") == curve.name:
            attach_cat_to_locomotion_curve(
                context,
                ctrl_obj=ctrl,
                curve_obj=curve,
                loop_path=bool(ctrl.get("cat_loop_anim", False)),
                flip_forward=bool(ctrl.get("cat_flip_curve_dir", False)),
                start_pct=float(ctrl.get("cat_curve_start_pct", 0.0)),
            )

        deg_now = math.degrees(float(targets[-1].tilt))
        self.report({"INFO"}, f"Curve point Tilt = {deg_now:+.1f}° on '{curve.name}'.")
        return {"FINISHED"}


class CAT_OT_bake_stray_biomechanics(Operator):
    bl_idname = "cat_director.bake_stray_biomechanics"
    bl_label = "Bake Stray Biomechanics Layer"
    bl_description = "Bake procedural Stray quadruped biomechanics (Spine S-bend, Tail Rudder, Head Lead, Blinks & Breathing)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            self.report({"WARNING"}, "Select a Black Cat actor first.")
            return {"CANCELLED"}
        res = bake_stray_biomechanics_layer(ctrl)
        if res.get("ok"):
            self.report(
                {"INFO"},
                f"Baked '{res.get('track')}' ({res.get('fcurves_count')} F-Curves, {res.get('blink_events')} blinks).",
            )
            return {"FINISHED"}
        self.report({"WARNING"}, f"Could not bake Stray biomechanics: {res.get('error')}")
        return {"CANCELLED"}


class CAT_OT_reset_pose_offsets(Operator):
    bl_idname = "cat_director.reset_pose_offsets"
    bl_label = "Reset Additive Pose Offsets"
    bl_description = "Reset additive Head, Spine, and Tail pose sliders to 0°"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            return {"CANCELLED"}
        clear_cat_additive_pose_offset(ctrl)
        set_cat_head_look_at_target(ctrl, weight=0.0)
        sync_ui_from_active_cat(ctrl, context.scene)
        self.report({"INFO"}, "Reset additive pose offsets.")
        return {"FINISHED"}


class CAT_OT_snap_ground_or_camera(Operator):
    bl_idname = "cat_director.snap_ground_or_camera"
    bl_label = "Snap / Align Cat"
    bl_description = "Snap cat paws to Z=0 ground plane or rotate to face the active camera"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        items=[
            ("GROUND", "Snap to Ground (Z=0)", ""),
            ("FACE_CAM", "Face Active Camera", ""),
            ("TOGGLE_BONES", "Toggle Rig Bones", ""),
        ],
        default="GROUND",
    )

    def execute(self, context):
        ctrl = find_cat_controller(context.active_object)
        if not ctrl:
            return {"CANCELLED"}

        if self.mode == "GROUND":
            ctrl.location.z = 0.0
        elif self.mode == "FACE_CAM":
            cam = context.scene.camera
            if cam:
                dx = cam.matrix_world.translation.x - ctrl.matrix_world.translation.x
                dy = cam.matrix_world.translation.y - ctrl.matrix_world.translation.y
                ctrl.rotation_euler.z = math.atan2(dx, -dy)
        elif self.mode == "TOGGLE_BONES":
            arm = find_cat_armature(ctrl)
            if arm:
                vis = any(b.is_visible for b in arm.data.collections)
                for b in arm.data.collections:
                    b.is_visible = not vis
                arm.show_in_front = not vis
        return {"FINISHED"}


# ============================================================================
# 4. N-PANEL UI (`View3D > Sidebar (N) > Black Cat Studio`)
# ============================================================================

class VIEW3D_PT_black_cat_director_studio(Panel):
    bl_label = "Black Cat Studio v2.0"
    bl_idname = "VIEW3D_PT_black_cat_director_studio"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Black Cat Studio"

    def draw(self, context):
        layout = self.layout
        scn = context.scene
        active_obj = context.active_object
        ctrl = find_cat_controller(active_obj)

        # If currently drawing a Curve in Edit Mode, show a prominent Finish & Bind banner at the top!
        if active_obj and active_obj.type == "CURVE" and getattr(active_obj, "mode", "OBJECT") == "EDIT":
            draw_box = layout.box()
            draw_box.alert = True
            col_d = draw_box.column(align=True)
            col_d.label(text=f"Drawing Curve: {active_obj.name}", icon="CURVE_BEZCURVE")
            col_d.label(text="Draw stroke in 3D Viewport, then click:", icon="INFO")
            row_fin = col_d.row(align=True)
            row_fin.scale_y = 1.6
            row_fin.operator(
                "cat_director.finish_draw_and_bind",
                text="2. Finish Drawing & Follow Curve",
                icon="CHECKMARK",
            )

        # --------------------------------------------------------------------
        # SECTION 1: SPAWN & 3D FUR COAT (FURLESS VIEWPORT BY DEFAULT)
        # --------------------------------------------------------------------
        box_actor = layout.box()
        row_hdr = box_actor.row(align=True)
        row_hdr.label(text="1. Black Cat Actor & 3D Fur Coat", icon="OUTLINER_OB_ARMATURE")
        row_hdr.operator("cat_director.load_database", text="", icon="FILE_REFRESH")

        row_spawn = box_actor.row(align=True)
        row_spawn.scale_y = 1.35
        row_spawn.operator("cat_director.spawn_cat", text="+ Spawn Black Cat", icon="ADD")

        if not ctrl:
            box_actor.label(text="Click '+ Spawn Black Cat' or select a cat.", icon="INFO")
            return

        meshes = find_cat_meshes(ctrl)
        body_m = meshes.get("body")
        ps_mod = body_m.modifiers.get("PS_Cat_FurCoat") if body_m else None
        vp_fur_on = bool(ps_mod.show_viewport) if ps_mod else bool(ctrl.get("cat_fur_viewport", False))
        ren_fur_on = bool(ps_mod.show_render) if ps_mod else bool(ctrl.get("cat_fur_render", True))

        box_actor.label(text=f"Active Cat: {ctrl.name}", icon="CHECKMARK")

        # Fur Coat Sub-Box
        fur_box = box_actor.box()
        fur_box.label(text="3D Fur Coat (180,000 Strands):", icon="STRANDS")
        row_fur_tog = fur_box.row(align=True)
        row_fur_tog.scale_y = 1.2
        row_fur_tog.operator(
            "cat_director.toggle_viewport_fur",
            text="Viewport Fur: ON" if vp_fur_on else "Viewport Fur: OFF (Fast)",
            icon="HIDE_OFF" if vp_fur_on else "HIDE_ON",
            depress=vp_fur_on,
        )
        row_fur_tog.operator(
            "cat_director.toggle_render_fur",
            text="Render Fur: ON" if ren_fur_on else "Render Fur: OFF",
            icon="RESTRICT_RENDER_OFF" if ren_fur_on else "RESTRICT_RENDER_ON",
            depress=ren_fur_on,
        )
        row_fur_sliders = fur_box.row(align=True)
        row_fur_sliders.prop(scn, "cat_dir_fur_length_mm", text="Length (mm)")
        row_fur_sliders.prop(scn, "cat_dir_fur_children", text="Density")

        col_t = box_actor.column(align=True)
        col_t.prop(scn, "cat_dir_look_mode", text="Coat Look")
        col_t.prop(scn, "cat_dir_char_scale", text="Cat Scale")

        row_util = box_actor.row(align=True)
        op_g = row_util.operator("cat_director.snap_ground_or_camera", text="Snap Z=0", icon="IMPORT")
        op_g.mode = "GROUND"
        op_c = row_util.operator("cat_director.snap_ground_or_camera", text="Face Cam", icon="CAMERA_DATA")
        op_c.mode = "FACE_CAM"
        op_b = row_util.operator("cat_director.snap_ground_or_camera", text="Bones", icon="BONE_DATA")
        op_b.mode = "TOGGLE_BONES"

        # --------------------------------------------------------------------
        # SECTION 2: DRAW 3D CURVE & ZERO-SLIP CURVE LOCOMOTION
        # --------------------------------------------------------------------
        box_curve = layout.box()
        box_curve.label(text="2. Draw Curve & Zero-Slip Locomotion", icon="CURVE_BEZCURVE")

        row_draw = box_curve.row(align=True)
        row_draw.scale_y = 1.35
        row_draw.operator("cat_director.draw_curve_path", text="1. Draw Curve Path", icon="GREASEPENCIL")
        row_draw.operator("cat_director.finish_draw_and_bind", text="2. Finish & Follow", icon="CHECKMARK")

        row_presets_c = box_curve.row(align=True)
        op_sc = row_presets_c.operator("cat_director.create_preset_curve", text="S-Curve", icon="CURVE_PATH")
        op_sc.preset_shape = "S_CURVE"
        op_cc = row_presets_c.operator("cat_director.create_preset_curve", text="Circle Loop", icon="MESH_CIRCLE")
        op_cc.preset_shape = "CIRCLE"
        op_jc = row_presets_c.operator("cat_director.create_preset_curve", text="Ledge Jump", icon="IPO_ELASTIC")
        op_jc.preset_shape = "LEDGE_JUMP"

        box_curve.prop(scn, "cat_dir_target_curve", text="Curve")

        cname = ctrl.get("cat_attached_curve", "")
        cobj = bpy.data.objects.get(cname) if cname else scn.cat_dir_target_curve
        if cobj and cobj.type == "CURVE":
            clen = compute_curve_true_1d_length(cobj)
            box_curve.label(
                text=f"Bound: {cobj.name} ({clen:.2f} m) — Zero-Slip Active",
                icon="CHECKMARK" if cname else "INFO",
            )

        row_bind = box_curve.row(align=True)
        row_bind.scale_y = 1.25
        row_bind.operator("cat_director.attach_to_curve", text="Bind / Sync Cat to Curve", icon="CONSTRAINT")
        row_bind.operator("cat_director.detach_from_curve", text="Detach", icon="X")

        row_copt = box_curve.row(align=True)
        row_copt.prop(scn, "cat_dir_curve_start_pct", text="Start %")
        row_copt.prop(scn, "cat_dir_flip_curve", text="Flip Dir", toggle=True)

        row_tilt = box_curve.row(align=True)
        row_tilt.label(text="Point Tilt Yaw:", icon="DRIVER_ROTATIONAL_DIFFERENCE")
        op_tl = row_tilt.operator("cat_director.adjust_curve_point_tilt", text="-15°")
        op_tl.delta_deg = -15.0
        op_tl.reset_zero = False
        op_t0 = row_tilt.operator("cat_director.adjust_curve_point_tilt", text="0°")
        op_t0.delta_deg = 0.0
        op_t0.reset_zero = True
        op_tr = row_tilt.operator("cat_director.adjust_curve_point_tilt", text="+15°")
        op_tr.delta_deg = 15.0
        op_tr.reset_zero = False

        # --------------------------------------------------------------------
        # SECTION 3: NLA ANIMATION STACKER & EDITOR (ZERO-SLIP WALKING)
        # --------------------------------------------------------------------
        box_nla = layout.box()
        box_nla.label(text="3. NLA Animation Stacker & Editor", icon="NLA")

        # 1-Click Sequence Presets
        col_pre = box_nla.column(align=True)
        col_pre.label(text="Quick Multi-Clip Sequence Presets:")
        row_p1 = col_pre.row(align=True)
        op_p1 = row_p1.operator("cat_director.apply_preset_sequence", text="Walk -> Sit -> Lick -> Walk", icon="SEQ_SEQUENCER")
        op_p1.preset_id = "WALK_GROOM_WALK"
        op_p2 = row_p1.operator("cat_director.apply_preset_sequence", text="Walk + Jump Ledge", icon="IPO_ELASTIC")
        op_p2.preset_id = "WALK_JUMP_LEDGE"
        row_p2 = col_pre.row(align=True)
        op_p3 = row_p2.operator("cat_director.apply_preset_sequence", text="Pure Walk Curve", icon="MOD_FOLLOWPATH")
        op_p3.preset_id = "PURE_WALK"
        op_p4 = row_p2.operator("cat_director.apply_preset_sequence", text="Seated Groom & Idle", icon="PAUSE")
        op_p4.preset_id = "SEATED_GROOM"

        box_nla.separator()
        box_nla.prop(scn, "cat_dir_action_enum", text="Clip")

        act_sel = bpy.data.actions.get(scn.cat_dir_action_enum)
        if act_sel:
            v_str = get_cat_exact_stride_speed(ctrl, act_sel, speed_mult_override=scn.cat_dir_anim_speed)
            span_f = int(round(act_sel.frame_range[1] - act_sel.frame_range[0]))
            mode_txt = f"Locomotion ({v_str:.2f} m/s Zero-Slip)" if v_str > 0.01 else "Stationary (0.00 m/s)"
            box_nla.label(text=f"Span: {span_f}f | {mode_txt}", icon="ANIM_DATA")

        row_add = box_nla.row(align=True)
        row_add.scale_y = 1.25
        op_add = row_add.operator("cat_director.nla_add_clip", text="+ Add to NLA Stack", icon="NLA_PUSHDOWN")
        op_add.insert_at_playhead = False
        op_add.default_mode = "AUTO"
        op_ins = row_add.operator("cat_director.nla_add_clip", text="Insert @ Playhead", icon="TIME")
        op_ins.insert_at_playhead = True
        op_ins.default_mode = "AUTO"
        row_add.operator("cat_director.apply_single_action", text="Single Loop", icon="FILE_REFRESH")

        row_timing = box_nla.row(align=True)
        row_timing.prop(scn, "cat_dir_anim_speed", text="Speed")
        row_timing.prop(scn, "cat_dir_nla_blend_frames", text="Blend (f)")
        row_timing.prop(scn, "cat_dir_loop_anim", text="Loop", toggle=True)

        # Native Blender NLA Editor Bridge
        row_nla_ed = box_nla.row(align=True)
        row_nla_ed.operator("cat_director.open_nla_editor", text="Open NLA Editor", icon="NLA")
        row_nla_ed.operator("cat_director.nla_sync_manual", text="Sync Manual NLA Edits", icon="FILE_REFRESH")

        # Stacked NLA Strips List
        clips = get_cat_nla_sequence_clips(ctrl)
        if clips:
            col_c = box_nla.column(align=True)
            row_ch = col_c.row(align=True)
            row_ch.label(text=f"NLA Strip Stack ({len(clips)} strips):", icon="SEQ_STRIP_DUPLICATE")
            row_ch.operator("cat_director.nla_clear", text="Clear All", icon="TRASH")

            active_idx = max(0, min(len(clips) - 1, int(scn.cat_dir_active_strip_idx)))
            for c in clips:
                idx = c["index"]
                is_sel = (idx == active_idx)
                r = col_c.row(align=True)
                mode_tag = "FILL" if c["is_fill"] else "FIX"
                short_name = c["action_name"].replace("Cat_", "").replace("Cat ", "").split("(")[0].strip()

                op_sel = r.operator(
                    "cat_director.nla_select_strip",
                    text=f"{idx + 1}. {short_name} ({c['effective_repeat']:.1f}x | f{c['frame_start']}-{c['frame_end']})",
                    depress=is_sel,
                    icon="RADIOBUT_ON" if is_sel else "RADIOBUT_OFF",
                )
                op_sel.clip_index = idx
                op_sel.jump_playhead = True

                op_tf = r.operator(
                    "cat_director.nla_edit_strip",
                    text=mode_tag,
                    depress=c["is_fill"],
                )
                op_tf.clip_index = idx
                op_tf.operation = "TOGGLE_FILL"

                op_m = r.operator("cat_director.nla_edit_strip", text="-")
                op_m.clip_index = idx
                op_m.operation = "REP_MINUS"

                op_p = r.operator("cat_director.nla_edit_strip", text="+")
                op_p.clip_index = idx
                op_p.operation = "REP_PLUS"

                op_u = r.operator("cat_director.nla_edit_strip", text="", icon="TRIA_UP")
                op_u.clip_index = idx
                op_u.operation = "UP"

                op_d = r.operator("cat_director.nla_edit_strip", text="", icon="TRIA_DOWN")
                op_d.clip_index = idx
                op_d.operation = "DOWN"

                op_x = r.operator("cat_director.nla_edit_strip", text="", icon="X")
                op_x.clip_index = idx
                op_x.operation = "REMOVE"

            # Active Strip Inspector Box
            sel_c = clips[active_idx]
            insp_box = box_nla.box()
            row_insp_hdr = insp_box.row(align=True)
            row_insp_hdr.label(
                text=f"Edit Strip #{active_idx + 1}: f{sel_c['frame_start']}..f{sel_c['frame_end']} ({sel_c['u_start_pct']:.0f}%->{sel_c['u_end_pct']:.0f}% curve)",
                icon="PROPERTIES",
            )
            op_dup = row_insp_hdr.operator("cat_director.nla_edit_strip", text="Duplicate", icon="DUPLICATE")
            op_dup.clip_index = active_idx
            op_dup.operation = "DUPLICATE"

            insp_box.prop(scn, "cat_dir_strip_action_enum", text="Action")
            row_isp = insp_box.row(align=True)
            row_isp.prop(scn, "cat_dir_strip_mode", text="Curve Mode")
            row_isp.prop(scn, "cat_dir_strip_repeat", text="Repeats")
            row_isp2 = insp_box.row(align=True)
            row_isp2.prop(scn, "cat_dir_strip_speed", text="Speed Mult")
            row_isp2.prop(scn, "cat_dir_strip_blend", text="Blend In (f)")

        # --------------------------------------------------------------------
        # SECTION 4: STRAY BIOMECHANICS & ADDITIVE POSE LAYER
        # --------------------------------------------------------------------
        box_pose = layout.box()
        row_ph = box_pose.row(align=True)
        row_ph.label(text="4. Stray Biomechanics & Pose Offset", icon="POSE_HLT")
        row_ph.operator("cat_director.reset_pose_offsets", text="Reset", icon="LOOP_BACK")

        row_bio = box_pose.row(align=True)
        row_bio.scale_y = 1.2
        row_bio.operator(
            "cat_director.bake_stray_biomechanics",
            text="Bake Stray Biomechanics (Spine S-Bend & Blinks)",
            icon="MOD_PHYSICS",
        )

        col_p = box_pose.column(align=True)
        row_h = col_p.row(align=True)
        row_h.prop(scn, "cat_dir_pose_head_yaw", text="Head Yaw °")
        row_h.prop(scn, "cat_dir_pose_head_pitch", text="Head Pitch °")

        row_st = col_p.row(align=True)
        row_st.prop(scn, "cat_dir_pose_spine_arch", text="Spine Arch °")
        row_st.prop(scn, "cat_dir_pose_tail_pitch", text="Tail Pitch °")
        row_st.prop(scn, "cat_dir_pose_tail_wag", text="Tail Wag °")

        row_lk = col_p.row(align=True)
        row_lk.prop(scn, "cat_dir_look_target_obj", text="Look Target")
        row_lk.prop(scn, "cat_dir_look_at_weight", text="Weight", slider=True)


# ============================================================================
# 5. REGISTRATION
# ============================================================================

CLASSES = (
    CAT_OT_load_database,
    CAT_OT_spawn_cat,
    CAT_OT_toggle_viewport_fur,
    CAT_OT_toggle_render_fur,
    CAT_OT_apply_preset_sequence,
    CAT_OT_apply_single_action,
    CAT_OT_nla_add_clip,
    CAT_OT_nla_select_strip,
    CAT_OT_nla_edit_strip,
    CAT_OT_nla_clear,
    CAT_OT_open_nla_editor,
    CAT_OT_nla_sync_manual,
    CAT_OT_draw_curve_path,
    CAT_OT_finish_draw_and_bind,
    CAT_OT_create_preset_curve,
    CAT_OT_attach_to_curve,
    CAT_OT_detach_from_curve,
    CAT_OT_adjust_curve_point_tilt,
    CAT_OT_bake_stray_biomechanics,
    CAT_OT_reset_pose_offsets,
    CAT_OT_snap_ground_or_camera,
    VIEW3D_PT_black_cat_director_studio,
)


def register_properties():
    scn = bpy.types.Scene
    scn.cat_dir_look_mode = EnumProperty(
        name="Coat Look",
        items=[
            ("PURE_BLACK", "Pure Black Velvet (Default)", "Obsidian matte-velvet undercoat + glossy golden-green eyes + 180k 3D fur coat"),
            ("TUXEDO_BW", "Tuxedo Black & White", "Original black-and-white tuxedo markings with matte-velvet fur coat"),
        ],
        default="PURE_BLACK",
        update=_on_cat_transform_or_anim_Changed,
    )
    scn.cat_dir_fur_viewport = BoolProperty(
        name="Viewport 3D Fur",
        description="Show 3D fur strands in the 3D Viewport (keep OFF for fast animation playback)",
        default=False,
        update=_on_cat_fur_props_changed,
    )
    scn.cat_dir_fur_render = BoolProperty(
        name="Render 3D Fur",
        description="Show 180,000 3D fur strands in F12 / batch renders",
        default=True,
        update=_on_cat_fur_props_changed,
    )
    scn.cat_dir_fur_length_mm = FloatProperty(
        name="Fur Length (mm)",
        default=18.0,
        min=4.0,
        max=60.0,
        step=50,
        precision=1,
        update=_on_cat_fur_props_changed,
    )
    scn.cat_dir_fur_children = IntProperty(
        name="Fur Density (Children)",
        description="Interpolated children per guide hair (36 = 180,000 total strands)",
        default=36,
        min=4,
        max=100,
        update=_on_cat_fur_props_changed,
    )
    scn.cat_dir_char_scale = FloatProperty(
        name="Cat Scale",
        default=1.0,
        min=0.15,
        max=5.0,
        step=5,
        precision=2,
        update=_on_cat_transform_or_anim_Changed,
    )
    scn.cat_dir_action_enum = EnumProperty(
        name="Animation",
        items=_get_action_enum_items,
    )
    scn.cat_dir_anim_speed = FloatProperty(
        name="Playback Speed",
        default=1.0,
        min=0.1,
        max=4.0,
        step=5,
        precision=2,
        update=_on_cat_transform_or_anim_Changed,
    )
    scn.cat_dir_frame_offset = IntProperty(
        name="Start Frame Offset",
        default=0,
        min=0,
        max=5000,
        update=_on_cat_transform_or_anim_Changed,
    )
    scn.cat_dir_nla_blend_frames = IntProperty(
        name="Crossfade (Frames)",
        default=8,
        min=0,
        max=40,
    )
    scn.cat_dir_loop_anim = BoolProperty(
        name="Loop Sequence",
        default=False,
        update=_on_cat_transform_or_anim_Changed,
    )
    scn.cat_dir_target_curve = PointerProperty(
        name="Target 3D Curve",
        type=bpy.types.Object,
        poll=_poll_curve_object,
    )
    scn.cat_dir_curve_start_pct = FloatProperty(
        name="Start % on Curve",
        default=0.0,
        min=0.0,
        max=99.0,
        step=100,
        precision=1,
        update=_on_cat_transform_or_anim_Changed,
    )
    scn.cat_dir_flip_curve = BoolProperty(
        name="Flip Curve Direction",
        default=False,
        update=_on_cat_transform_or_anim_Changed,
    )

    # Active NLA Strip Inspector Properties
    scn.cat_dir_active_strip_idx = IntProperty(
        name="Active NLA Strip Index",
        default=0,
        min=0,
    )
    scn.cat_dir_strip_action_enum = EnumProperty(
        name="Strip Action",
        items=_get_action_enum_items,
        update=_on_active_strip_props_changed,
    )
    scn.cat_dir_strip_repeat = FloatProperty(
        name="Strip Repeats",
        default=1.0,
        min=0.1,
        max=50.0,
        step=25,
        precision=2,
        update=_on_active_strip_props_changed,
    )
    scn.cat_dir_strip_speed = FloatProperty(
        name="Strip Playback Speed",
        default=1.0,
        min=0.1,
        max=4.0,
        step=5,
        precision=2,
        update=_on_active_strip_props_changed,
    )
    scn.cat_dir_strip_blend = IntProperty(
        name="Strip Blend In (Frames)",
        default=8,
        min=0,
        max=40,
        update=_on_active_strip_props_changed,
    )
    scn.cat_dir_strip_mode = EnumProperty(
        name="Curve Locomotion Mode",
        items=[
            ("FILL", "FILL (Auto-Stretch Walk to Curve Length)", "Automatically calculates repeat count so this walking clip covers the curve with zero foot-slip"),
            ("FIXED", "FIXED (Exact Repeat Count Along Curve)", "Plays exact repeat count while advancing along the curve at exact stride speed with zero foot-slip"),
        ],
        default="FILL",
        update=_on_active_strip_props_changed,
    )

    # Additive Pose Offset Properties
    scn.cat_dir_pose_head_yaw = FloatProperty(
        name="Head Yaw °",
        default=0.0,
        min=-75.0,
        max=75.0,
        step=100,
        precision=1,
        update=_on_cat_pose_offset_changed,
    )
    scn.cat_dir_pose_head_pitch = FloatProperty(
        name="Head Pitch °",
        default=0.0,
        min=-55.0,
        max=55.0,
        step=100,
        precision=1,
        update=_on_cat_pose_offset_changed,
    )
    scn.cat_dir_pose_spine_arch = FloatProperty(
        name="Spine Arch °",
        default=0.0,
        min=-35.0,
        max=35.0,
        step=100,
        precision=1,
        update=_on_cat_pose_offset_changed,
    )
    scn.cat_dir_pose_tail_pitch = FloatProperty(
        name="Tail Pitch °",
        default=0.0,
        min=-60.0,
        max=60.0,
        step=100,
        precision=1,
        update=_on_cat_pose_offset_changed,
    )
    scn.cat_dir_pose_tail_wag = FloatProperty(
        name="Tail Wag °",
        default=0.0,
        min=-65.0,
        max=65.0,
        step=100,
        precision=1,
        update=_on_cat_pose_offset_changed,
    )
    scn.cat_dir_look_target_obj = PointerProperty(
        name="Look Target Object",
        type=bpy.types.Object,
        update=_on_cat_pose_offset_changed,
    )
    scn.cat_dir_look_at_weight = FloatProperty(
        name="Head Look-At Weight",
        default=0.0,
        min=0.0,
        max=1.0,
        precision=2,
        update=_on_cat_pose_offset_changed,
    )


def unregister_properties():
    scn = bpy.types.Scene
    for prop in (
        "cat_dir_look_mode",
        "cat_dir_fur_viewport",
        "cat_dir_fur_render",
        "cat_dir_fur_length_mm",
        "cat_dir_fur_children",
        "cat_dir_char_scale",
        "cat_dir_action_enum",
        "cat_dir_anim_speed",
        "cat_dir_frame_offset",
        "cat_dir_nla_blend_frames",
        "cat_dir_loop_anim",
        "cat_dir_target_curve",
        "cat_dir_curve_start_pct",
        "cat_dir_flip_curve",
        "cat_dir_active_strip_idx",
        "cat_dir_strip_action_enum",
        "cat_dir_strip_repeat",
        "cat_dir_strip_speed",
        "cat_dir_strip_blend",
        "cat_dir_strip_mode",
        "cat_dir_pose_head_yaw",
        "cat_dir_pose_head_pitch",
        "cat_dir_pose_spine_arch",
        "cat_dir_pose_tail_pitch",
        "cat_dir_pose_tail_wag",
        "cat_dir_look_target_obj",
        "cat_dir_look_at_weight",
    ):
        if hasattr(scn, prop):
            try:
                delattr(scn, prop)
            except Exception:
                pass


def register_ui():
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except Exception:
            pass
    register_properties()
    if _cat_selection_redirect_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_cat_selection_redirect_handler)


def unregister_ui():
    if _cat_selection_redirect_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_cat_selection_redirect_handler)
    unregister_properties()
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass
