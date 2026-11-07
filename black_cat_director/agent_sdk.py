# -*- coding: utf-8 -*-
"""
Black Cat Animation Director Studio v2.0 — High-Level Python & AI Agent SDK
===========================================================================
Clean 1-function-call Python API (`black_cat_director.agent_sdk`) for human
animators and AI agents to integrate the rigged Black Cat actor, 180,000-strand
3D Fur Coat (furless in viewport by default, full 3D fur in render), 3D Curve
Locomotion (zero foot-slip), Multi-Clip NLA Sequencer, and Stray Biomechanics
into ANY `.blend` project.
"""

import math
import bpy

from .constants import (
    DEFAULT_IDLE_ACTION,
    PRESET_PURE_WALK_CURVE,
    PRESET_SEATED_GROOMING_IDLE,
    PRESET_WALK_JUMP_LEDGE,
    PRESET_WALK_STOP_GROOM_WALK,
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
)
from .nla_sequencer import (
    append_cat_animation_to_nla,
    apply_cat_additive_pose_offset,
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
from .operators_ui import register_ui, sync_ui_from_active_cat
from .rig_actors import (
    configure_cat_fur_coat,
    configure_cat_look,
    find_cat_controller,
    spawn_cat_actor,
)


def integrate_cat_studio(
    spawn_demo: bool = True,
    preset: str = "WALK_GROOM_WALK",
    viewport_fur: bool = False,
    render_fur: bool = True,
) -> dict:
    """
    One-call integration for any `.blend` file:
      1. Registers the `Black Cat Studio v2.0` N-Panel (`View3D > Sidebar (N) > Black Cat Studio`),
      2. Loads the rigged Black Cat template, 180,000-strand 3D fur coat, and 29 animations
         from `database/cat_assets_library.blend`,
      3. Optionally spawns `CTRL_Cat_01` (`viewport_fur=False` for fast animation, `render_fur=True`
         for full 3D fur in renders) on a 3D Bezier curve (`Cat_Path_01`) with a zero-slip NLA sequence.
    """
    register_ui()
    ensure_cat_database_loaded()
    scan_and_import_dropin_cat_animations()

    result = {
        "database_loaded": True,
        "available_actions": len(list_available_cat_actions()),
        "cat_controller": None,
        "curve": None,
    }

    if spawn_demo:
        ctrl = spawn_cat_actor(
            name="CTRL_Cat_01",
            location=(0.0, 0.0, 0.0),
            rotation_z_deg=0.0,
            scale=1.0,
            look_mode="PURE_BLACK",
            viewport_fur=viewport_fur,
            render_fur=render_fur,
        )
        preset_key = str(preset or "WALK_GROOM_WALK").upper()
        if preset_key == "WALK_JUMP_LEDGE":
            curve = create_cat_walk_curve(name="Cat_Path_01", preset_shape="LEDGE_JUMP")
            specs = PRESET_WALK_JUMP_LEDGE
        elif preset_key == "PURE_WALK":
            curve = create_cat_walk_curve(name="Cat_Path_01", preset_shape="S_CURVE")
            specs = PRESET_PURE_WALK_CURVE
        elif preset_key == "SEATED_GROOM":
            curve = None
            specs = PRESET_SEATED_GROOMING_IDLE
        else:
            curve = create_cat_walk_curve(name="Cat_Path_01", preset_shape="S_CURVE")
            specs = PRESET_WALK_STOP_GROOM_WALK

        if curve:
            ctrl["cat_attached_curve"] = curve.name
            if getattr(bpy.context, "scene", None):
                bpy.context.scene.cat_dir_target_curve = curve
            rebuild_cat_nla_sequence_from_specs(ctrl, specs, sync_curve=True)
            result["curve"] = curve.name
        else:
            rebuild_cat_nla_sequence_from_specs(ctrl, specs, sync_curve=False)

        sync_ui_from_active_cat(ctrl)
        result["cat_controller"] = ctrl.name

    return result


def spawn_cat(
    name: str = "CTRL_Cat_01",
    location=(0.0, 0.0, 0.0),
    rotation_z_deg: float = 0.0,
    scale: float = 1.0,
    look_mode: str = "PURE_BLACK",
    initial_action: str = DEFAULT_IDLE_ACTION,
    viewport_fur: bool = False,
    render_fur: bool = True,
):
    """Spawns or updates a rigged Black Cat actor (`CTRL_Cat_XX`) with furless viewport by default."""
    return spawn_cat_actor(
        name=name,
        location=location,
        rotation_z_deg=rotation_z_deg,
        scale=scale,
        look_mode=look_mode,
        initial_action=initial_action,
        viewport_fur=viewport_fur,
        render_fur=render_fur,
    )


def set_cat_fur_coat(
    cat_or_name="CTRL_Cat_01",
    viewport_fur: bool = None,
    render_fur: bool = None,
    fur_length_m: float = None,
    fur_children: int = None,
) -> dict:
    """Configures viewport/render visibility, strand length, and density of the 3D fur coat."""
    ctrl = bpy.data.objects.get(cat_or_name) if isinstance(cat_or_name, str) else cat_or_name
    ctrl = find_cat_controller(ctrl)
    return configure_cat_fur_coat(
        ctrl,
        viewport_fur=viewport_fur,
        render_fur=render_fur,
        fur_length_m=fur_length_m,
        fur_children=fur_children,
    )


def create_cat_curve(
    name: str = "Cat_Path_01",
    points=None,
    cyclic: bool = False,
    preset_shape: str = "S_CURVE",
):
    """Creates or updates a 3D Bezier curve path (`points` = list of `(x, y, z)` tuples)."""
    return create_cat_walk_curve(
        name=name,
        points=points,
        cyclic=cyclic,
        preset_shape=preset_shape,
    )


def bind_cat_to_curve(
    cat_or_name="CTRL_Cat_01",
    curve_or_name="Cat_Path_01",
    loop_path: bool = False,
    flip_forward: bool = False,
    start_pct: float = 0.0,
) -> tuple:
    """Binds a Black Cat actor to a 3D curve and bakes zero-slip locomotion keyframes."""
    ctrl = bpy.data.objects.get(cat_or_name) if isinstance(cat_or_name, str) else cat_or_name
    curve = bpy.data.objects.get(curve_or_name) if isinstance(curve_or_name, str) else curve_or_name
    ctrl = find_cat_controller(ctrl)
    return attach_cat_to_locomotion_curve(
        bpy.context,
        ctrl_obj=ctrl,
        curve_obj=curve,
        loop_path=loop_path,
        flip_forward=flip_forward,
        start_pct=start_pct,
    )


def set_cat_nla_sequence(cat_or_name="CTRL_Cat_01", clip_specs=None, sync_curve: bool = True) -> tuple:
    """
    Builds a multi-clip NLA sequence on the specified cat controller (`CTRL_Cat_01`).
    Each element in `clip_specs` can be a dict:
      `{"action": "Cat_Walk (1_32)", "repeat": 1.0, "speed": 1.0, "blend": 8, "mode": "FILL"}`
    """
    ctrl = bpy.data.objects.get(cat_or_name) if isinstance(cat_or_name, str) else cat_or_name
    ctrl = find_cat_controller(ctrl)
    if clip_specs is None:
        clip_specs = PRESET_WALK_STOP_GROOM_WALK
    return rebuild_cat_nla_sequence_from_specs(ctrl, clip_specs, sync_curve=sync_curve)


def add_cat_nla_clip(
    cat_or_name="CTRL_Cat_01",
    action_name: str = "Cat_Walk (1_32)",
    repeat: float = 1.0,
    speed: float = 1.0,
    blend: int = 8,
    mode: str = "AUTO",
) -> tuple:
    """Appends a single animation clip to the end of the cat's NLA stack and syncs the curve."""
    ctrl = bpy.data.objects.get(cat_or_name) if isinstance(cat_or_name, str) else cat_or_name
    ctrl = find_cat_controller(ctrl)
    return append_cat_animation_to_nla(
        ctrl,
        action_name=action_name,
        repeat_count=repeat,
        blend_frames=blend,
        speed_mult=speed,
        mode=mode,
    )


def edit_cat_nla_clip(
    cat_or_name="CTRL_Cat_01",
    index: int = 0,
    action_name: str = None,
    repeat: float = None,
    speed: float = None,
    blend: int = None,
    mode: str = None,
) -> tuple:
    """Edits the properties of an existing NLA strip at `index` and re-solves zero-slip curve locomotion."""
    ctrl = bpy.data.objects.get(cat_or_name) if isinstance(cat_or_name, str) else cat_or_name
    ctrl = find_cat_controller(ctrl)
    return update_cat_nla_clip_properties(
        ctrl,
        index=index,
        action_name=action_name,
        repeat=repeat,
        speed=speed,
        blend=blend,
        mode=mode,
    )


def sync_manual_nla_edits(cat_or_name="CTRL_Cat_01", sync_curve: bool = True) -> tuple:
    """Reads manual strip edits from Blender's NLA Editor and re-solves zero-slip curve locomotion."""
    ctrl = bpy.data.objects.get(cat_or_name) if isinstance(cat_or_name, str) else cat_or_name
    ctrl = find_cat_controller(ctrl)
    return sync_manual_nla_edits_to_specs(ctrl, sync_curve=sync_curve)


def set_cat_pose_offset(
    cat_or_name="CTRL_Cat_01",
    head_yaw_deg: float = 0.0,
    head_pitch_deg: float = 0.0,
    spine_arch_deg: float = 0.0,
    tail_pitch_deg: float = 0.0,
    tail_wag_deg: float = 0.0,
    look_at_target=None,
    look_at_weight: float = 0.0,
) -> bool:
    """Applies non-destructive additive pose offsets (`COMBINE` NLA layer) and optional Head Look-At target."""
    ctrl = bpy.data.objects.get(cat_or_name) if isinstance(cat_or_name, str) else cat_or_name
    ctrl = find_cat_controller(ctrl)
    if not ctrl:
        return False
    apply_cat_additive_pose_offset(
        ctrl,
        head_yaw_deg=head_yaw_deg,
        head_pitch_deg=head_pitch_deg,
        spine_arch_deg=spine_arch_deg,
        tail_pitch_deg=tail_pitch_deg,
        tail_wag_deg=tail_wag_deg,
    )
    if look_at_target is not None or look_at_weight > 0.0:
        tgt = bpy.data.objects.get(look_at_target) if isinstance(look_at_target, str) else look_at_target
        set_cat_head_look_at_target(ctrl, target_obj=tgt, weight=look_at_weight)
    return True


__all__ = [
    "integrate_cat_studio",
    "spawn_cat",
    "set_cat_fur_coat",
    "create_cat_curve",
    "bind_cat_to_curve",
    "set_cat_nla_sequence",
    "add_cat_nla_clip",
    "edit_cat_nla_clip",
    "sync_manual_nla_edits",
    "set_cat_pose_offset",
    "ensure_cat_database_loaded",
    "list_available_cat_actions",
    "get_cat_nla_sequence_clips",
    "configure_cat_look",
    "configure_cat_fur_coat",
    "compute_curve_true_1d_length",
    "bake_stray_biomechanics_layer",
    "duplicate_cat_nla_clip",
    "move_cat_nla_clip",
    "remove_cat_nla_clip_at_index",
    "toggle_cat_nla_clip_fill_mode",
    "clear_cat_nla_sequence",
    "detach_cat_from_curve",
]
