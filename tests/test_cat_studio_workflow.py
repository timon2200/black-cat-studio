# -*- coding: utf-8 -*-
"""
Automated End-to-End Test Suite for Black Cat Animation Director Studio v2.0
============================================================================
Run in a fresh Blender instance:
  /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P tests/test_cat_studio_workflow.py
"""

import math
import os
import sys
import bpy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import black_cat_director as cd


def run_tests():
    print("=== [Test 1] Register Plugin & Load Database in Fresh Blender Scene ===")
    res = cd.integrate_cat_studio(spawn_demo=False)
    assert res["database_loaded"] is True, "Database failed to load!"
    assert res["available_actions"] >= 25, f"Expected >=25 actions, got {res['available_actions']}"
    print(f"  -> Loaded {res['available_actions']} animations.")

    print("=== [Test 2] Spawn Black Cat Actor & Verify Furless Viewport / Render Fur ON ===")
    cat = cd.spawn_cat("CTRL_Cat_01", location=(0.0, 0.0, 0.0), viewport_fur=False, render_fur=True)
    assert cat is not None and cat.name == "CTRL_Cat_01"
    body = bpy.data.objects.get("MESH_Cat_01_Body")
    fur_cards = bpy.data.objects.get("MESH_Cat_01_Fur")
    assert body is not None, "MESH_Cat_01_Body not found!"
    ps_mod = body.modifiers.get("PS_Cat_FurCoat")
    assert ps_mod is not None, "PS_Cat_FurCoat modifier missing on MESH_Cat_01_Body!"
    assert ps_mod.show_viewport is False, "Viewport Fur must be OFF by default for fast animation!"
    assert ps_mod.show_render is True, "Render Fur must be ON by default!"
    pset = ps_mod.particle_system.settings
    assert pset.count == 5000 and pset.rendered_child_count == 36, "Expected 5000x36 = 180,000 fur strands!"
    if fur_cards:
        assert fur_cards.hide_viewport is True and fur_cards.hide_render is True
    print(f"  -> Verified PS_Cat_FurCoat: show_viewport={ps_mod.show_viewport}, show_render={ps_mod.show_render}, strands={pset.count * pset.rendered_child_count:,}")

    print("=== [Test 3] Draw Curve Path Operator & Custom 3D Curve Creation ===")
    bpy.ops.cat_director.draw_curve_path()
    drawn_curve = bpy.context.active_object
    assert drawn_curve is not None and drawn_curve.type == "CURVE", "draw_curve_path did not create a curve!"
    # Populate custom drawn points on the curve and finish drawing
    bpy.ops.object.mode_set(mode="OBJECT")
    cd.create_cat_curve(
        name=drawn_curve.name,
        points=[
            (-1.50, 1.20, 0.0),
            (-0.50, 0.50, 0.0),
            (0.50, -0.20, 0.0),
            (1.40, -1.00, 0.0),
        ],
    )
    bpy.ops.cat_director.finish_draw_and_bind()
    arc_len = cd.compute_curve_true_1d_length(drawn_curve)
    assert arc_len > 2.0, f"Expected curve length > 2.0m, got {arc_len}"
    print(f"  -> Drawn curve '{drawn_curve.name}' length = {arc_len:.3f} m, bound to '{cat.name}'.")

    print("=== [Test 4] Stack & Edit Animations in NLA Sequencer + Verify Zero-Slip Locomotion ===")
    cd.clear_cat_nla_sequence(cat)
    cd.add_cat_nla_clip(cat, "Cat idle (1_143)", repeat=0.25, blend=0, mode="FIXED")
    cd.add_cat_nla_clip(cat, "Cat_Walk (1_32)", repeat=2.0, blend=6, mode="FIXED")
    cd.add_cat_nla_clip(cat, "Cat sitting (1-24)", repeat=1.0, blend=6, mode="FIXED")
    cd.add_cat_nla_clip(cat, "Cat_Seated_Paw_Lick (1_104)", repeat=0.5, blend=6, mode="FIXED")
    cd.add_cat_nla_clip(cat, "Cat Standing  (1-24)", repeat=1.0, blend=6, mode="FIXED")
    cd.add_cat_nla_clip(cat, "Cat_Walk (1_32)", repeat=1.0, blend=6, mode="FILL")

    clips = cd.get_cat_nla_sequence_clips(cat)
    assert len(clips) == 6, f"Expected 6 NLA clips, got {len(clips)}"

    # Verify zero drift during stationary Paw Lick clip (clip index 3)
    lick_clip = clips[3]
    f_lick_mid1 = lick_clip["frame_start"] + 10
    f_lick_mid2 = lick_clip["frame_end"] - 10
    bpy.context.scene.frame_set(f_lick_mid1)
    p_lick1 = cat.matrix_world.translation.copy()
    bpy.context.scene.frame_set(f_lick_mid2)
    p_lick2 = cat.matrix_world.translation.copy()
    lick_drift = (p_lick2 - p_lick1).length
    assert lick_drift < 1e-4, f"Stationary clip drifted by {lick_drift:.6f} m!"
    print(f"  -> Stationary clip drift = {lick_drift:.6f} m (0.00 mm stationary lock verified).")

    # Verify exact zero-slip stride speed (0.32 m/s) during FIXED walk clip (clip index 1)
    walk_clip = clips[1]
    f_w1 = walk_clip["frame_start"] + 12
    f_w2 = walk_clip["frame_end"] - 12
    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    dist_walked = 0.0
    bpy.context.scene.frame_set(f_w1)
    prev_p = cat.matrix_world.translation.copy()
    for f in range(f_w1 + 1, f_w2 + 1):
        bpy.context.scene.frame_set(f)
        cur_p = cat.matrix_world.translation.copy()
        dist_walked += (cur_p - prev_p).length
        prev_p = cur_p
    dt_sec = (f_w2 - f_w1) / fps
    measured_speed = dist_walked / dt_sec
    expected_speed = 0.32
    slip_err = abs(measured_speed - expected_speed)
    assert slip_err < 0.015, f"Walk speed {measured_speed:.4f} m/s deviated from {expected_speed:.4f} m/s!"
    print(f"  -> Measured Walk Speed = {measured_speed:.4f} m/s vs Calibrated Stride Speed = {expected_speed:.4f} m/s (Zero-Slip verified!).")

    print("=== [Test 5] Test Manual NLA Editor Sync ===")
    ok_sync, msg_sync = cd.sync_manual_nla_edits(cat, sync_curve=True)
    assert ok_sync is True, f"sync_manual_nla_edits failed: {msg_sync}"
    print(f"  -> {msg_sync}")

    print("ALL_CAT_STUDIO_TESTS_PASSED")


if __name__ == "__main__":
    run_tests()
