# -*- coding: utf-8 -*-
"""
Black Cat Animation Director Studio v2.0 (`black_cat_director`)
===============================================================
Standalone, general-purpose Blender 4.x / 5.x Add-on & AI Agent SDK for
quadruped black cat animation, featuring:
  - Rigged 69-bone Quadruped Black Cat Actor (`CTRL_Cat_01`) with automatic
    viewport click-redirection,
  - 180,000-Strand 3D Feline Fur Coat (`PS_Cat_FurCoat`: 5,000 guides x 36 interpolated
    children, 3D `STRIP` hair, anatomical `VG_Fur_Density` & `VG_Fur_Length`),
  - Furless 3D Viewport by default (`show_viewport = False`) for fast animation playback,
    and full 3D fur in Render (`show_render = True`),
  - Matte-Velvet Undercoat + Glossy Golden-Green Eye Mask (`cat body`) & Whiskers (`CAT_Whiskers_Mat`),
  - Interactive 3D Curve Drawing (`Draw Curve Path`) & Zero-Slip Curve Locomotion,
  - Multi-Clip NLA Animation Stacker & Strip Inspector + Native Blender NLA Editor Sync,
  - Stray-Style Procedural Quadruped Biomechanics (Spine S-Bend, Tail Rudder, Head Lead,
    Eyelid Blinks, Asymmetric Ear Twitches & Breathing).
"""

bl_info = {
    "name": "Black Cat Animation Director Studio v2.0",
    "author": "Studio Varazdin",
    "version": (2, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (N) > Black Cat Studio",
    "description": "Rigged Black Cat Actor, 180k-Strand 3D Fur Coat (Furless Viewport / Full Render), Zero-Slip 3D Curve Locomotion, NLA Animation Stacker & Stray Biomechanics",
    "category": "Animation",
}

import importlib

from . import (
    constants,
    database,
    rig_actors,
    locomotion,
    nla_sequencer,
    operators_ui,
    agent_sdk,
)


def reload_all_submodules():
    for mod in (
        constants,
        database,
        rig_actors,
        locomotion,
        nla_sequencer,
        operators_ui,
        agent_sdk,
    ):
        importlib.reload(mod)


from .agent_sdk import (
    integrate_cat_studio,
    spawn_cat,
    set_cat_fur_coat,
    create_cat_curve,
    bind_cat_to_curve,
    set_cat_nla_sequence,
    add_cat_nla_clip,
    edit_cat_nla_clip,
    sync_manual_nla_edits,
    set_cat_pose_offset,
    ensure_cat_database_loaded,
    list_available_cat_actions,
    get_cat_nla_sequence_clips,
    configure_cat_look,
    configure_cat_fur_coat,
    compute_curve_true_1d_length,
    bake_stray_biomechanics_layer,
    duplicate_cat_nla_clip,
    move_cat_nla_clip,
    remove_cat_nla_clip_at_index,
    toggle_cat_nla_clip_fill_mode,
    clear_cat_nla_sequence,
    detach_cat_from_curve,
)


def register():
    operators_ui.register_ui()


def unregister():
    operators_ui.unregister_ui()


if __name__ == "__main__":
    register()
