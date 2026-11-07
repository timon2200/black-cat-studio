# -*- coding: utf-8 -*-
"""
Black Cat Animation Director Studio v2.0 — Multi-Layer NLA Sequencer & Stray Biomechanics
=========================================================================================
Manages:
  1. Multi-clip NLA sequence stacking (`CAT_Director_Sequence` + `CAT_Layer_*`)
     with automatic `REPLACE` crossfading (`blend_in`), `HOLD` / `NOTHING` extrapolation,
     and bidirectional sync with Blender's native NLA Editor (`sync_manual_nla_edits_to_specs`),
  2. Non-destructive `COMBINE` additive pose offset layer (`CAT_Additive_PoseOffset`) on top
     of the NLA stack for Head Yaw/Pitch, Spine Arch, Tail Pitch/Wag,
  3. Live 3D Head Look-At Target tracking (`DAMPED_TRACK` on `head`),
  4. Procedural 'Stray' AAA Quadruped Biomechanics (`CAT_Stray_Biomechanics`):
     Spine S-Bend & Tail Counterweight Rudder around curve turns, Head-Lead Target
     Anticipation, Torso/Shoulder Weight Shift, Eyelid Blinks, Ear Twitches & Breathing.
"""

import json
import math
import bpy
from mathutils import Euler

from .constants import (
    DEFAULT_JUMP_ACTION,
    DEFAULT_LOOK_AROUND_ACTION,
    DEFAULT_PAW_LICK_ACTION,
    DEFAULT_PAW_REACH_ACTION,
    DEFAULT_SIT_ACTION,
    EYELID_CLOSED_LOCATIONS,
    STRAY_BIOMECH_TRACK_NAME,
    bind_action_slot,
    get_action_fcurves,
    resolve_action_name,
)
from .database import set_action_cyclic_loop
from .rig_actors import find_cat_controller, get_cat_armature_from_ctrl


def get_cat_nla_sequence_tracks(arm_obj) -> list:
    if not arm_obj or not arm_obj.animation_data:
        return []
    return [
        tr for tr in arm_obj.animation_data.nla_tracks
        if tr.name.startswith("CAT_Director_Sequence") or tr.name.startswith("CAT_Layer_")
    ]


def _extract_and_remove_additive_track(adt):
    if not adt:
        return None
    saved_act = None
    for tr in list(adt.nla_tracks):
        if tr.name.startswith("CAT_Additive_PoseOffset"):
            for s in tr.strips:
                if s.action:
                    saved_act = s.action
            adt.nla_tracks.remove(tr)
    return saved_act


def _append_additive_track_on_top(adt, offset_act):
    if not adt or not offset_act:
        return None
    for tr in list(adt.nla_tracks):
        if tr.name.startswith("CAT_Additive_PoseOffset"):
            adt.nla_tracks.remove(tr)
    add_track = adt.nla_tracks.new()
    add_track.name = "CAT_Additive_PoseOffset"
    strip = add_track.strips.new(offset_act.name, 1, offset_act)
    strip.frame_start = 1.0
    strip.frame_end = 10000.0
    strip.blend_type = "COMBINE"
    strip.extrapolation = "HOLD"
    bind_action_slot(strip, offset_act)
    return add_track


def assign_cat_action_with_slot(arm_obj, action, speed_mult=1.0, frame_offset=0, loop_enabled=True) -> bool:
    if not arm_obj or not action:
        return False
    if not arm_obj.animation_data:
        arm_obj.animation_data_create()
    adt = arm_obj.animation_data

    set_action_cyclic_loop(action, enabled=loop_enabled)

    seq_tracks = get_cat_nla_sequence_tracks(arm_obj)
    if any(len(tr.strips) > 0 for tr in seq_tracks):
        adt.action = None
        return True

    has_additive = any(tr.name.startswith("CAT_Additive_PoseOffset") for tr in adt.nla_tracks)
    use_nla_playback = (abs(float(speed_mult) - 1.0) > 1e-3) or (abs(int(frame_offset)) > 0) or has_additive

    for tr in list(adt.nla_tracks):
        if tr.name.startswith("CAT_AutoPlayback"):
            adt.nla_tracks.remove(tr)

    if use_nla_playback:
        saved_add = _extract_and_remove_additive_track(adt)
        adt.action = None

        track = adt.nla_tracks.new()
        track.name = "CAT_AutoPlayback"
        start_f = max(1, 1 + int(frame_offset))
        strip = track.strips.new(action.name, start_f, action)
        strip.scale = 1.0 / max(0.1, float(speed_mult))
        strip.repeat = 40.0 if loop_enabled else 1.0
        strip.blend_type = "REPLACE"
        strip.extrapolation = "HOLD"
        bind_action_slot(strip, action)

        if saved_add:
            _append_additive_track_on_top(adt, saved_add)
    else:
        adt.action = action
        bind_action_slot(adt, action)

    return True


def get_cat_nla_sequence_clips(ctrl_obj) -> list:
    ctrl_obj = find_cat_controller(ctrl_obj)
    arm_obj = get_cat_armature_from_ctrl(ctrl_obj)
    if not arm_obj or not arm_obj.animation_data:
        return []

    seq_tracks = get_cat_nla_sequence_tracks(arm_obj)
    if not seq_tracks:
        return []

    stored_specs = []
    raw_json = ctrl_obj.get("cat_nla_sequence_json", "") if ctrl_obj else ""
    if raw_json:
        try:
            stored_specs = json.loads(raw_json)
        except Exception:
            stored_specs = []

    raw_items = []
    for tr in seq_tracks:
        if len(tr.strips) > 0:
            raw_items.append((tr, tr.strips[0]))
    raw_items.sort(key=lambda item: (int(round(item[1].frame_start)), item[0].name))

    from .locomotion import solve_cat_nla_curve_timing_plan
    plan = solve_cat_nla_curve_timing_plan(ctrl_obj, stored_specs) if stored_specs else {"clips": []}
    plan_clips = plan.get("clips", [])

    clips = []
    for idx, (tr, s) in enumerate(raw_items):
        p_info = plan_clips[idx] if idx < len(plan_clips) else {}
        spec_info = stored_specs[idx] if idx < len(stored_specs) else {}
        act_name = s.action.name if s.action else p_info.get("action", "")
        act = bpy.data.actions.get(act_name)
        label = str(act.get("cat_label", act_name)) if act else act_name
        clips.append({
            "index": idx,
            "track_name": tr.name,
            "strip_name": s.name,
            "action_name": act_name,
            "label": label,
            "frame_start": int(round(s.frame_start)),
            "frame_end": int(round(s.frame_end)),
            "scale": round(float(s.scale), 3),
            "speed": round(1.0 / max(0.1, float(s.scale)), 2),
            "repeat": round(float(spec_info.get("repeat", s.repeat)), 2),
            "effective_repeat": round(float(p_info.get("effective_repeat", s.repeat)), 2),
            "blend_in": round(float(s.blend_in), 1),
            "mode": str(spec_info.get("mode", p_info.get("mode", "AUTO"))),
            "is_fill": bool(p_info.get("is_fill", False)),
            "speed_mps": float(p_info.get("speed_mps", 0.0)),
            "u_start_pct": float(p_info.get("u_start_pct", 0.0)),
            "u_end_pct": float(p_info.get("u_end_pct", 100.0)),
            "u_mid_pct": float(p_info.get("u_mid_pct", 50.0)),
        })
    return clips


def sync_manual_nla_edits_to_specs(ctrl_obj, sync_curve: bool = True) -> tuple:
    """
    Reads the actual NLA strips on `arm_obj` (including any manual edits the user
    performed directly in Blender's NLA Editor: reordering, changing repeats/length,
    scale, or blend_in), updates `cat_nla_sequence_json`, and re-solves the zero-slip
    curve trajectory so walking strips never drag their feet!
    """
    ctrl_obj = find_cat_controller(ctrl_obj)
    arm_obj = get_cat_armature_from_ctrl(ctrl_obj)
    if not ctrl_obj or not arm_obj or not arm_obj.animation_data:
        return False, "No Black Cat actor or NLA data found."

    adt = arm_obj.animation_data
    raw_strips = []
    for tr in adt.nla_tracks:
        if tr.name.startswith("CAT_Additive_PoseOffset") or tr.name.startswith(STRAY_BIOMECH_TRACK_NAME):
            continue
        for s in tr.strips:
            if s.action and not s.name.endswith(("_Loop2", "_Loop3", "_Loop4", "_Loop5", "_Loop6", "_Loop7", "_Loop8")):
                raw_strips.append((tr, s))

    if not raw_strips:
        return False, "No NLA strips found to sync."

    raw_strips.sort(key=lambda item: (float(item[1].frame_start), item[0].name))
    specs = []
    for idx, (_tr, s) in enumerate(raw_strips):
        act = s.action
        f_span = max(1.0, float(act.frame_range[1] - act.frame_range[0]))
        spd = round(1.0 / max(0.1, float(s.scale)), 3)
        single_len = max(1.0, f_span / spd)
        strip_len = max(1.0, float(s.frame_end - s.frame_start))
        # Calculate effective repeat from either strip.repeat or manual frame_end resize
        rep_from_len = round(strip_len / single_len, 2)
        rep = max(0.1, rep_from_len if abs(rep_from_len - float(s.repeat)) > 0.05 else round(float(s.repeat), 2))
        bld = 0 if idx == 0 else max(0, int(round(float(s.blend_in))))
        specs.append({
            "action": act.name,
            "repeat": rep,
            "speed": spd,
            "blend": bld,
            "mode": "FIXED",
        })

    return rebuild_cat_nla_sequence_from_specs(ctrl_obj, specs, sync_curve=sync_curve)


def rebuild_cat_nla_sequence_from_specs(ctrl_obj, clip_specs, sync_curve: bool = True) -> tuple:
    """
    Rebuilds the cat's multi-clip NLA sequence tracks from `clip_specs`:
      - Solves `effective_repeat` for `FILL` locomotion loops (`Cat_Walk`, `Cat _Run`, etc.),
      - Builds clean layered NLA tracks (`CAT_Director_Sequence`, `CAT_Layer_01`, ...) with
        smooth `blend_in` crossfades,
      - Automatically updates the 3D locomotion curve keyframes (`PathAnim_<ctrl_obj.name>`)
        and bakes the Stray biomechanical layer (`CAT_Stray_Biomechanics`).
    """
    ctrl_obj = find_cat_controller(ctrl_obj)
    if not ctrl_obj:
        return False, "No Black Cat controller (CTRL_Cat) selected."
    arm_obj = get_cat_armature_from_ctrl(ctrl_obj)
    if not arm_obj:
        return False, f"Armature not found for '{ctrl_obj.name}'."

    if not arm_obj.animation_data:
        arm_obj.animation_data_create()
    adt = arm_obj.animation_data

    normalized = []
    for i, spec in enumerate(clip_specs or []):
        if isinstance(spec, str):
            act_name = spec
            rep = 1.0
            spd = float(ctrl_obj.get("cat_anim_speed", 1.0))
            bld = 0 if i == 0 else 8
            mode = "AUTO"
        elif isinstance(spec, dict):
            act_name = spec.get("action") or spec.get("action_name") or spec.get("name") or ""
            rep = float(spec.get("repeat", 1.0))
            spd = float(spec.get("speed", ctrl_obj.get("cat_anim_speed", 1.0)))
            bld = int(round(float(spec.get("blend", spec.get("blend_in", 0 if i == 0 else 8)))))
            mode = str(spec.get("mode", "AUTO")).upper()
        else:
            continue

        act_name = resolve_action_name(act_name)
        act = bpy.data.actions.get(act_name)
        if not act:
            continue
        normalized.append({
            "action": act.name,
            "repeat": max(0.1, round(rep, 2)),
            "speed": max(0.1, round(spd, 3)),
            "blend": 0 if len(normalized) == 0 else max(0, bld),
            "mode": mode if mode in ("AUTO", "FILL", "FIXED") else "AUTO",
        })

    if not normalized:
        return False, "No valid animations provided for NLA sequence."

    from .locomotion import solve_cat_nla_curve_timing_plan, attach_cat_to_locomotion_curve

    curve_name = ctrl_obj.get("cat_attached_curve", "")
    curve_obj = bpy.data.objects.get(curve_name) if curve_name else None

    plan = solve_cat_nla_curve_timing_plan(ctrl_obj, normalized, curve_obj=curve_obj)
    plan_clips = plan["clips"]
    cycle_frames = max(4, int(plan["cycle_frames"]))

    saved_add = _extract_and_remove_additive_track(adt)

    for tr in list(adt.nla_tracks):
        if (
            tr.name.startswith("CAT_AutoPlayback")
            or tr.name.startswith("CAT_Director_Sequence")
            or tr.name.startswith("CAT_Layer_")
            or tr.name.startswith(STRAY_BIOMECH_TRACK_NAME)
        ):
            adt.nla_tracks.remove(tr)

    adt.action = None

    base_offset = max(0, int(ctrl_obj.get("cat_frame_offset", 0)))
    start_base = 1 + base_offset
    loop_anim = bool(ctrl_obj.get("cat_loop_anim", False))

    tracks = []
    for idx in range(len(plan_clips)):
        tr = adt.nla_tracks.new()
        tr.name = "CAT_Director_Sequence" if idx == 0 else f"CAT_Layer_{idx:02d}"
        tracks.append(tr)

    num_cycles = max(2, min(8, int(math.ceil(1200.0 / max(10, cycle_frames))))) if loop_anim else 1

    for cyc in range(num_cycles):
        cyc_offset = start_base + cyc * cycle_frames
        for idx, pclip in enumerate(plan_clips):
            act = bpy.data.actions.get(pclip["action"])
            if not act:
                continue
            tr = tracks[idx]
            f_start = int(cyc_offset + pclip["tau_start"])
            eff_rep = float(pclip["effective_repeat"])
            eff_bld = int(pclip["eff_blend"]) if idx > 0 else 0

            strip_name = act.name if cyc == 0 else f"{act.name}_Loop{cyc + 1}"
            strip = tr.strips.new(strip_name, f_start, act)
            strip.scale = 1.0 / max(0.1, float(pclip["speed"]))
            strip.repeat = max(0.1, eff_rep)
            strip.blend_type = "REPLACE"

            if idx == 0:
                strip.extrapolation = "HOLD"
            elif not loop_anim and cyc == num_cycles - 1 and idx == len(plan_clips) - 1:
                strip.extrapolation = "HOLD_FORWARD"
            else:
                strip.extrapolation = "NOTHING"

            strip.use_auto_blend = False
            strip.blend_in = float(eff_bld)
            strip.blend_out = 0.0
            bind_action_slot(strip, act)

    if saved_add:
        _append_additive_track_on_top(adt, saved_add)

    ctrl_obj["cat_nla_sequence_json"] = json.dumps(normalized)
    ctrl_obj["cat_anim_name"] = normalized[-1]["action"]

    if sync_curve and curve_obj and curve_obj.type == "CURVE":
        attach_cat_to_locomotion_curve(
            bpy.context,
            ctrl_obj=ctrl_obj,
            curve_obj=curve_obj,
            loop_path=loop_anim,
            flip_forward=bool(ctrl_obj.get("cat_flip_curve_dir", False)),
            start_pct=float(ctrl_obj.get("cat_curve_start_pct", 0.0)),
            _from_nla_rebuild=True,
        )
    else:
        bake_stray_biomechanics_layer(ctrl_obj)
        if bpy.context and getattr(bpy.context, "scene", None):
            bpy.context.scene.frame_start = 1
            bpy.context.scene.frame_end = max(cycle_frames, start_base + cycle_frames - 1)

    summary = " -> ".join(f"{c['action'].split('(')[0].strip()}" for c in plan_clips)
    return True, f"NLA Sequence ({len(plan_clips)} clips, {cycle_frames}f): {summary}"


def append_cat_animation_to_nla(
    ctrl_obj,
    action_name: str,
    repeat_count: float = 1.0,
    blend_frames: int = 8,
    speed_mult: float = None,
    mode: str = "AUTO",
) -> tuple:
    ctrl_obj = find_cat_controller(ctrl_obj)
    if not ctrl_obj:
        return False, "Select a Black Cat actor (CTRL_Cat)."
    action_name = resolve_action_name(action_name)
    act = bpy.data.actions.get(action_name)
    if not act:
        return False, f"Animation '{action_name}' not found."

    if speed_mult is None:
        speed_mult = float(ctrl_obj.get("cat_anim_speed", 1.0))

    existing_clips = get_cat_nla_sequence_clips(ctrl_obj)
    specs = []
    if existing_clips:
        raw_json = ctrl_obj.get("cat_nla_sequence_json", "")
        if raw_json:
            try:
                specs = json.loads(raw_json)
            except Exception:
                specs = []
        if not specs:
            for c in existing_clips:
                specs.append({
                    "action": c["action_name"],
                    "repeat": c["repeat"],
                    "speed": round(1.0 / max(0.1, c["scale"]), 2),
                    "blend": int(round(c["blend_in"])),
                    "mode": c.get("mode", "AUTO"),
                })

    specs.append({
        "action": act.name,
        "repeat": max(0.1, float(repeat_count)),
        "speed": max(0.1, float(speed_mult)),
        "blend": 0 if len(specs) == 0 else max(0, int(blend_frames)),
        "mode": str(mode).upper(),
    })
    return rebuild_cat_nla_sequence_from_specs(ctrl_obj, specs, sync_curve=True)


def update_cat_nla_clip_properties(
    ctrl_obj,
    index: int,
    action_name: str = None,
    repeat: float = None,
    speed: float = None,
    blend: int = None,
    mode: str = None,
) -> tuple:
    """Updates any property of the NLA clip at `index` and re-solves zero-slip curve locomotion."""
    ctrl_obj = find_cat_controller(ctrl_obj)
    if not ctrl_obj:
        return False, "No Black Cat actor selected."
    raw_json = ctrl_obj.get("cat_nla_sequence_json", "")
    specs = json.loads(raw_json) if raw_json else []
    if not (0 <= index < len(specs)):
        return False, "Invalid NLA strip index."

    if action_name is not None:
        resolved = resolve_action_name(action_name)
        if bpy.data.actions.get(resolved):
            specs[index]["action"] = resolved
    if repeat is not None:
        specs[index]["repeat"] = max(0.1, round(float(repeat), 2))
    if speed is not None:
        specs[index]["speed"] = max(0.1, round(float(speed), 3))
    if blend is not None:
        specs[index]["blend"] = 0 if index == 0 else max(0, int(blend))
    if mode is not None:
        specs[index]["mode"] = str(mode).upper()

    return rebuild_cat_nla_sequence_from_specs(ctrl_obj, specs, sync_curve=True)


def duplicate_cat_nla_clip(ctrl_obj, index: int) -> tuple:
    ctrl_obj = find_cat_controller(ctrl_obj)
    if not ctrl_obj:
        return False, "No Black Cat actor selected."
    raw_json = ctrl_obj.get("cat_nla_sequence_json", "")
    specs = json.loads(raw_json) if raw_json else []
    if not (0 <= index < len(specs)):
        return False, "Invalid NLA strip index."
    dup = dict(specs[index])
    dup["blend"] = max(6, int(dup.get("blend", 8)))
    specs.insert(index + 1, dup)
    return rebuild_cat_nla_sequence_from_specs(ctrl_obj, specs, sync_curve=True)


def remove_cat_nla_clip_at_index(ctrl_obj, index: int) -> tuple:
    ctrl_obj = find_cat_controller(ctrl_obj)
    if not ctrl_obj:
        return False, "No Black Cat actor selected."
    raw_json = ctrl_obj.get("cat_nla_sequence_json", "")
    specs = json.loads(raw_json) if raw_json else []
    if not (0 <= index < len(specs)):
        return False, "Invalid NLA strip index."
    removed = specs.pop(index)
    if not specs:
        clear_cat_nla_sequence(ctrl_obj)
        return True, f"Removed last NLA strip ({removed.get('action')})."
    specs[0]["blend"] = 0
    return rebuild_cat_nla_sequence_from_specs(ctrl_obj, specs, sync_curve=True)


def move_cat_nla_clip(ctrl_obj, index: int, direction: int) -> tuple:
    ctrl_obj = find_cat_controller(ctrl_obj)
    if not ctrl_obj:
        return False, "No Black Cat actor selected."
    raw_json = ctrl_obj.get("cat_nla_sequence_json", "")
    specs = json.loads(raw_json) if raw_json else []
    new_idx = index + int(direction)
    if not (0 <= index < len(specs)) or not (0 <= new_idx < len(specs)):
        return False, "Strip is already at the end of the stack."
    specs[index], specs[new_idx] = specs[new_idx], specs[index]
    specs[0]["blend"] = 0
    for i in range(1, len(specs)):
        if specs[i].get("blend", 0) == 0:
            specs[i]["blend"] = 8
    return rebuild_cat_nla_sequence_from_specs(ctrl_obj, specs, sync_curve=True)


def adjust_cat_nla_clip_repeat(ctrl_obj, index: int, delta: float) -> tuple:
    ctrl_obj = find_cat_controller(ctrl_obj)
    if not ctrl_obj:
        return False, "No Black Cat actor selected."
    raw_json = ctrl_obj.get("cat_nla_sequence_json", "")
    specs = json.loads(raw_json) if raw_json else []
    if not (0 <= index < len(specs)):
        return False, "Invalid NLA strip index."
    cur = float(specs[index].get("repeat", 1.0))
    specs[index]["repeat"] = max(0.15, round(cur + float(delta), 2))
    specs[index]["mode"] = "FIXED"
    return rebuild_cat_nla_sequence_from_specs(ctrl_obj, specs, sync_curve=True)


def toggle_cat_nla_clip_fill_mode(ctrl_obj, index: int) -> tuple:
    ctrl_obj = find_cat_controller(ctrl_obj)
    if not ctrl_obj:
        return False, "No Black Cat actor selected."
    raw_json = ctrl_obj.get("cat_nla_sequence_json", "")
    specs = json.loads(raw_json) if raw_json else []
    if not (0 <= index < len(specs)):
        return False, "Invalid NLA strip index."
    cur_mode = str(specs[index].get("mode", "AUTO")).upper()
    clips = get_cat_nla_sequence_clips(ctrl_obj)
    is_currently_fill = clips[index]["is_fill"] if index < len(clips) else (cur_mode == "FILL")
    specs[index]["mode"] = "FIXED" if is_currently_fill else "FILL"
    return rebuild_cat_nla_sequence_from_specs(ctrl_obj, specs, sync_curve=True)


def clear_cat_nla_sequence(ctrl_obj) -> bool:
    ctrl_obj = find_cat_controller(ctrl_obj)
    arm_obj = get_cat_armature_from_ctrl(ctrl_obj)
    if not arm_obj or not arm_obj.animation_data:
        return False
    adt = arm_obj.animation_data
    for tr in list(adt.nla_tracks):
        if (
            tr.name.startswith("CAT_Director_Sequence")
            or tr.name.startswith("CAT_Layer_")
            or tr.name.startswith(STRAY_BIOMECH_TRACK_NAME)
        ):
            adt.nla_tracks.remove(tr)
    ctrl_obj["cat_nla_sequence_json"] = ""
    act_name = resolve_action_name(ctrl_obj.get("cat_anim_name", "Cat idle (1_143)"))
    act = bpy.data.actions.get(act_name)
    if act:
        assign_cat_action_with_slot(
            arm_obj,
            act,
            speed_mult=float(ctrl_obj.get("cat_anim_speed", 1.0)),
            frame_offset=int(ctrl_obj.get("cat_frame_offset", 0)),
            loop_enabled=bool(ctrl_obj.get("cat_loop_anim", True)),
        )
    return True


def apply_cat_additive_pose_offset(
    ctrl_obj,
    head_yaw_deg: float = 0.0,
    head_pitch_deg: float = 0.0,
    spine_arch_deg: float = 0.0,
    tail_pitch_deg: float = 0.0,
    tail_wag_deg: float = 0.0,
) -> bool:
    """
    Applies a non-destructive `COMBINE` NLA layer (`CAT_Additive_PoseOffset`) on top of
    any active cat animation or NLA sequence.
    """
    ctrl_obj = find_cat_controller(ctrl_obj)
    arm_obj = get_cat_armature_from_ctrl(ctrl_obj)
    if not ctrl_obj or not arm_obj:
        return False

    ctrl_obj["cat_pose_head_yaw"] = float(head_yaw_deg)
    ctrl_obj["cat_pose_head_pitch"] = float(head_pitch_deg)
    ctrl_obj["cat_pose_spine_arch"] = float(spine_arch_deg)
    ctrl_obj["cat_pose_tail_pitch"] = float(tail_pitch_deg)
    ctrl_obj["cat_pose_tail_wag"] = float(tail_wag_deg)

    is_zero = (
        abs(head_yaw_deg) < 1e-3
        and abs(head_pitch_deg) < 1e-3
        and abs(spine_arch_deg) < 1e-3
        and abs(tail_pitch_deg) < 1e-3
        and abs(tail_wag_deg) < 1e-3
    )
    if is_zero:
        clear_cat_additive_pose_offset(ctrl_obj)
        return True

    if not arm_obj.animation_data:
        arm_obj.animation_data_create()
    adt = arm_obj.animation_data

    if adt.action is not None:
        cur_act = adt.action
        assign_cat_action_with_slot(
            arm_obj,
            cur_act,
            speed_mult=float(ctrl_obj.get("cat_anim_speed", 1.0)),
            frame_offset=int(ctrl_obj.get("cat_frame_offset", 0)),
            loop_enabled=bool(ctrl_obj.get("cat_loop_anim", True)),
        )

    act_name = f"CAT_PoseOffset_{ctrl_obj.name}"
    offset_act = bpy.data.actions.get(act_name)
    if offset_act:
        bpy.data.actions.remove(offset_act, do_unlink=True)
    offset_act = bpy.data.actions.new(name=act_name)

    if hasattr(offset_act, "layers"):
        layer = offset_act.layers.new(name="Layer") if len(offset_act.layers) == 0 else offset_act.layers[0]
        strip = layer.strips.new(type="KEYFRAME") if len(layer.strips) == 0 else layer.strips[0]
        slot = offset_act.slots.new(id_type="OBJECT", name=f"OB{arm_obj.name}") if len(offset_act.slots) == 0 else offset_act.slots[0]
        fcs = strip.channelbag(slot, ensure=True).fcurves
    else:
        fcs = offset_act.fcurves

    bone_rotations = {
        "head": Euler((math.radians(head_pitch_deg * 0.70), 0.0, math.radians(head_yaw_deg * 0.70)), "XYZ").to_quaternion(),
        "neck": Euler((math.radians(head_pitch_deg * 0.30), 0.0, math.radians(head_yaw_deg * 0.30)), "XYZ").to_quaternion(),
        "chest": Euler((math.radians(spine_arch_deg * 0.60), 0.0, 0.0), "XYZ").to_quaternion(),
        "tail_master.001": Euler((math.radians(tail_pitch_deg), 0.0, math.radians(tail_wag_deg)), "XYZ").to_quaternion(),
    }

    for bname, quat in bone_rotations.items():
        if bname not in arm_obj.pose.bones:
            continue
        dp = f'pose.bones["{bname}"].rotation_quaternion'
        for idx in range(4):
            fc = fcs.new(data_path=dp, index=idx)
            kp1 = fc.keyframe_points.insert(1.0, float(quat[idx]))
            kp2 = fc.keyframe_points.insert(100.0, float(quat[idx]))
            kp1.interpolation = "CONSTANT"
            kp2.interpolation = "CONSTANT"
            fc.update()

    _append_additive_track_on_top(adt, offset_act)
    return True


def clear_cat_additive_pose_offset(ctrl_obj) -> bool:
    ctrl_obj = find_cat_controller(ctrl_obj)
    arm_obj = get_cat_armature_from_ctrl(ctrl_obj)
    if not ctrl_obj or not arm_obj or not arm_obj.animation_data:
        return False
    adt = arm_obj.animation_data
    for tr in list(adt.nla_tracks):
        if tr.name.startswith("CAT_Additive_PoseOffset"):
            adt.nla_tracks.remove(tr)
    act_name = f"CAT_PoseOffset_{ctrl_obj.name}"
    old_act = bpy.data.actions.get(act_name)
    if old_act:
        try:
            bpy.data.actions.remove(old_act, do_unlink=True)
        except Exception:
            pass
    for k in ("cat_pose_head_yaw", "cat_pose_head_pitch", "cat_pose_spine_arch", "cat_pose_tail_pitch", "cat_pose_tail_wag"):
        ctrl_obj[k] = 0.0
    return True


def set_cat_head_look_at_target(ctrl_obj, target_obj=None, weight: float = 0.0):
    """
    Configures or updates a live `DAMPED_TRACK` constraint on the cat's `head` bone
    pointing toward `target_obj` with `influence = weight` (`0.0 .. 1.0`).
    """
    ctrl_obj = find_cat_controller(ctrl_obj)
    arm_obj = get_cat_armature_from_ctrl(ctrl_obj)
    if not ctrl_obj or not arm_obj or "head" not in arm_obj.pose.bones:
        return False

    pb_head = arm_obj.pose.bones["head"]
    con_name = "CAT_Head_LookAt_Target"
    con = pb_head.constraints.get(con_name) or pb_head.constraints.get("CAT_Head_LookAt_Lift")
    if weight <= 1e-3 or not target_obj:
        if con:
            con.influence = 0.0
        ctrl_obj["cat_look_at_target_weight"] = 0.0
        return True

    if not con:
        con = pb_head.constraints.new(type="DAMPED_TRACK")
        con.name = con_name
    con.target = target_obj
    con.track_axis = "TRACK_Y"
    con.influence = max(0.0, min(1.0, float(weight)))
    ctrl_obj["cat_look_at_target_weight"] = float(con.influence)
    return True


def _smoothstep01(x: float) -> float:
    t = max(0.0, min(1.0, float(x)))
    return t * t * (3.0 - 2.0 * t)


def _window_bell(f: float, f_start: float, f_peak_s: float, f_peak_e: float, f_end: float) -> float:
    if f <= f_start or f >= f_end:
        return 0.0
    if f < f_peak_s:
        return _smoothstep01((f - f_start) / max(1e-4, f_peak_s - f_start))
    if f <= f_peak_e:
        return 1.0
    return 1.0 - _smoothstep01((f - f_peak_e) / max(1e-4, f_end - f_peak_e))


def _blink_pulse(f: float, f_start: float, duration: float = 6.0, close_frames: float = 2.0, peak: float = 1.0) -> float:
    if f <= f_start or f >= f_start + duration:
        return 0.0
    dt = f - f_start
    if dt <= close_frames:
        return peak * _smoothstep01(dt / max(0.5, close_frames))
    open_span = max(1.0, duration - close_frames)
    return peak * (1.0 - _smoothstep01((dt - close_frames) / open_span))


def bake_stray_biomechanics_layer(ctrl_obj) -> dict:
    """
    Bakes the 4 procedural 'Stray' AAA Quadruped Biomechanical Layers onto a non-destructive
    `COMBINE` NLA track (`CAT_Stray_Biomechanics` / action `CAT_StrayBiomech_<ctrl_obj.name>`):
      1. Spine & Tail Curvature Deformation (S-bend & Counterweight Rudder around curve turns),
      2. Head-Lead Target Anticipation (leads turns by 6-7 frames, pitches up before jumps),
      3. Torso/Chest Weight Shift & Shoulder Compression (jump takeoff crouch & landing absorption),
      4. Secondary Life (Eyelid Blinks, Asymmetric Ear Micro-Twitches & Rhythmic Chest Breathing).
    """
    ctrl_obj = find_cat_controller(ctrl_obj)
    arm_obj = get_cat_armature_from_ctrl(ctrl_obj)
    if not ctrl_obj or not arm_obj:
        return {"ok": False, "error": "Controller or armature not found"}

    if not arm_obj.animation_data:
        arm_obj.animation_data_create()
    adt = arm_obj.animation_data

    clips = get_cat_nla_sequence_clips(ctrl_obj)
    if not clips:
        return {"ok": False, "error": "No NLA clips on armature"}

    start_f = min(int(c["frame_start"]) for c in clips)
    end_f = max(int(c["frame_end"]) for c in clips)
    total_frames = max(4, end_f - start_f + 1)

    saved_add = _extract_and_remove_additive_track(adt)
    for tr in list(adt.nla_tracks):
        if tr.name.startswith(STRAY_BIOMECH_TRACK_NAME):
            adt.nla_tracks.remove(tr)

    act_name = f"CAT_StrayBiomech_{ctrl_obj.name}"
    old_act = bpy.data.actions.get(act_name)
    if old_act:
        bpy.data.actions.remove(old_act, do_unlink=True)
    bio_act = bpy.data.actions.new(name=act_name)
    bio_act.use_fake_user = True

    if hasattr(bio_act, "layers"):
        layer = bio_act.layers.new(name="Layer") if len(bio_act.layers) == 0 else bio_act.layers[0]
        strip_k = layer.strips.new(type="KEYFRAME") if len(layer.strips) == 0 else layer.strips[0]
        slot = bio_act.slots.new(id_type="OBJECT", name=f"OB{arm_obj.name}") if len(bio_act.slots) == 0 else bio_act.slots[0]
        fcs = strip_k.channelbag(slot, ensure=True).fcurves
    else:
        fcs = bio_act.fcurves

    pa = bpy.data.actions.get(f"PathAnim_{ctrl_obj.name}")
    rot_z_fc = None
    if pa:
        for fc in get_action_fcurves(pa):
            if fc.data_path == "rotation_euler" and int(fc.array_index) == 2:
                rot_z_fc = fc
                break

    yaw_series = {}
    for f in range(start_f - 12, end_f + 15):
        fc_eval_f = float(max(start_f, min(end_f, f)))
        yaw_series[f] = float(rot_z_fc.evaluate(fc_eval_f)) if rot_z_fc else 0.0

    raw_omega = {}
    for f in range(start_f - 10, end_f + 13):
        raw_omega[f] = 0.5 * (yaw_series[f + 1] - yaw_series[f - 1])

    smooth_omega = {}
    for f in range(start_f - 8, end_f + 11):
        smooth_omega[f] = (
            0.10 * raw_omega[f - 2]
            + 0.20 * raw_omega[f - 1]
            + 0.40 * raw_omega[f]
            + 0.20 * raw_omega[f + 1]
            + 0.10 * raw_omega[f + 2]
        )
    omega_z = {}
    for f in range(start_f - 6, end_f + 9):
        omega_z[f] = (
            0.10 * smooth_omega[f - 2]
            + 0.20 * smooth_omega[f - 1]
            + 0.40 * smooth_omega[f]
            + 0.20 * smooth_omega[f + 1]
            + 0.10 * smooth_omega[f + 2]
        )

    def _kappa_at(f_query: float) -> float:
        fi = int(round(max(start_f - 6, min(end_f + 8, f_query))))
        return max(-1.25, min(1.25, -omega_z.get(fi, 0.0) / 0.032))

    walk_clips = [c for c in clips if "walk" in c["action_name"].lower() or "run" in c["action_name"].lower()]
    jump_clip = next((c for c in clips if DEFAULT_JUMP_ACTION in c["action_name"] or "jump" in c["action_name"].lower()), None)
    sit_clip = next((c for c in clips if DEFAULT_SIT_ACTION in c["action_name"] or "sitting" in c["action_name"].lower()), None)
    lick_clip = next((c for c in clips if DEFAULT_PAW_LICK_ACTION in c["action_name"] or "paw_lick" in c["action_name"].lower()), None)
    reach_clip = next((c for c in clips if DEFAULT_PAW_REACH_ACTION in c["action_name"] or "paw_reach" in c["action_name"].lower()), None)
    look_clip = next((c for c in clips if DEFAULT_LOOK_AROUND_ACTION in c["action_name"] or "look_around" in c["action_name"].lower()), None)

    js = float(jump_clip["frame_start"]) if jump_clip else -999.0
    je = float(jump_clip["frame_end"]) if jump_clip else -999.0
    sit_s = float(sit_clip["frame_start"]) if sit_clip else (je + 25.0 if jump_clip else 151.0)
    sit_e = float(sit_clip["frame_end"]) if sit_clip else (sit_s + 23.0)
    ls = float(lick_clip["frame_start"]) if lick_clip else -999.0
    le = float(lick_clip["frame_end"]) if lick_clip else -999.0
    lvs = float(reach_clip["frame_start"]) if reach_clip else -999.0
    lve = float(reach_clip["frame_end"]) if reach_clip else -999.0
    ws = float(look_clip["frame_start"]) if look_clip else -999.0

    quat_bones = [
        "torso", "hips", "chest",
        "spine_fk", "spine_fk.001", "spine_fk.002", "spine_fk.003",
        "neck", "head", "ear.L", "ear.R", "tail_master.001",
    ]
    loc_bones = ["torso", "chest", "shoulder.L", "shoulder.R"] + list(EYELID_CLOSED_LOCATIONS.keys())
    euler_bones = ["shoulder.L", "shoulder.R"]

    quat_tracks = {b: [] for b in quat_bones if b in arm_obj.pose.bones}
    loc_tracks = {b: [] for b in loc_bones if b in arm_obj.pose.bones}
    euler_tracks = {b: [] for b in euler_bones if b in arm_obj.pose.bones}

    blink_events_scheduled = []
    for k_b in range(start_f + 32, end_f - 10, 64):
        blink_events_scheduled.append((f"auto_blink_{k_b}", float(k_b), 6.0, 1.0))
    if jump_clip:
        blink_events_scheduled.append(("pre_jump_turn", js - 11.0, 6.0, 1.0))
    if sit_clip:
        blink_events_scheduled.append(("post_sit_settle", sit_e + 3.0, 6.0, 1.0))
    if lick_clip:
        blink_events_scheduled.append(("lick_finish_clear", le - 8.0, 6.0, 1.0))

    for f_int in range(start_f, end_f + 1):
        f = float(f_int)

        k_head = _kappa_at(f + 7.0)
        k_neck = _kappa_at(f + 6.0)
        k_chest = _kappa_at(f + 3.0)
        k_sp3 = _kappa_at(f + 3.0)
        k_sp2 = _kappa_at(f + 1.0)
        k_sp1 = _kappa_at(f - 1.0)
        k_sp0 = _kappa_at(f - 2.0)
        k_hips = _kappa_at(f - 3.0)
        k_tail = _kappa_at(f - 3.0)

        walk_env = 0.0
        for wc in walk_clips:
            walk_env = max(walk_env, _window_bell(f, wc["frame_start"], wc["frame_start"] + 5, wc["frame_end"] - 5, wc["frame_end"]))
        cadence_sway_deg = 2.4 * walk_env * math.sin(2.0 * math.pi * (f - start_f) / 16.0)

        head_z_deg = 17.5 * k_head
        head_y_deg = -5.0 * k_head
        head_x_deg = 0.0

        neck_z_deg = 13.5 * k_neck
        neck_y_deg = -3.8 * k_neck
        neck_x_deg = 0.0

        chest_z_deg = 11.5 * k_chest + 0.6 * cadence_sway_deg
        chest_y_deg = -4.2 * k_chest
        chest_x_deg = 0.0

        sp3_z_deg = 9.8 * k_sp3 + 0.8 * cadence_sway_deg
        sp2_z_deg = 8.8 * k_sp2 + 1.0 * cadence_sway_deg
        sp1_z_deg = 6.8 * k_sp1 - 0.5 * cadence_sway_deg
        sp0_z_deg = 4.5 * k_sp0 - 0.6 * cadence_sway_deg
        hips_z_deg = -4.2 * k_hips

        tail_z_deg = -24.0 * k_tail - 2.2 * cadence_sway_deg
        tail_x_deg = 10.5 * abs(k_tail)
        if sit_clip and f >= sit_s - 4.0 and f <= sit_e + 22.0:
            dt_osc = f - (sit_s - 4.0)
            tail_z_deg += 13.5 * math.exp(-0.105 * dt_osc) * math.sin(0.42 * dt_osc)

        torso_dx = -0.006 * k_chest
        torso_dy = 0.0
        torso_dz = 0.0
        torso_rx_deg = 0.0
        torso_ry_deg = -2.0 * k_chest
        torso_rz_deg = 3.0 * k_chest

        chest_dx = -0.008 * k_chest
        chest_dy = 0.0
        chest_dz = 0.0

        shL_dx, shL_dy, shL_dz = 0.0, 0.0, 0.0
        shR_dx, shR_dy, shR_dz = 0.0, 0.0, 0.0
        shL_rx, shL_ry, shL_rz = 0.0, 0.0, 0.0
        shR_rx, shR_ry, shR_rz = 0.0, 0.0, 0.0

        if jump_clip:
            w_pre_jump = _window_bell(f, js - 14.0, js - 7.0, js + 2.0, js + 8.0)
            head_x_deg += -19.5 * w_pre_jump
            head_z_deg += 7.5 * w_pre_jump
            neck_x_deg += -9.5 * w_pre_jump
            neck_z_deg += 4.0 * w_pre_jump

            w_land_look = _window_bell(f, js + 12.0, js + 17.0, je - 2.0, je + 5.0)
            head_x_deg += 15.5 * w_land_look
            neck_x_deg += 7.0 * w_land_look

            w_crouch = _window_bell(f, js - 4.0, js, js + 3.0, js + 7.0)
            torso_dz += -0.022 * w_crouch
            chest_dz += -0.012 * w_crouch
            chest_x_deg += 8.5 * w_crouch
            shL_dz += 0.011 * w_crouch
            shR_dz += 0.011 * w_crouch

            w_air_arch = _window_bell(f, js + 8.0, js + 11.0, js + 16.0, js + 20.0)
            chest_x_deg += -4.5 * w_air_arch

            w_impact = _window_bell(f, je - 7.0, je - 3.0, je, je + 6.0)
            torso_dz += -0.024 * w_impact
            torso_dy += -0.014 * w_impact
            chest_dz += -0.014 * w_impact
            chest_x_deg += 9.5 * w_impact
            shL_dz += 0.014 * w_impact
            shR_dz += 0.014 * w_impact
            shL_rx += math.radians(6.5) * w_impact
            shR_rx += math.radians(6.5) * w_impact

        if lick_clip:
            w_lick_look = _window_bell(f, ls + 1.0, ls + 5.0, ls + 14.0, ls + 24.0)
            head_x_deg += 5.5 * w_lick_look
            head_z_deg += -6.5 * w_lick_look

        if reach_clip:
            w_lev_ant = _window_bell(f, lvs - 2.0, lvs + 4.0, lvs + 13.0, lvs + 22.0)
            head_x_deg += 4.0 * w_lev_ant
            head_z_deg += -5.0 * w_lev_ant
            neck_x_deg += 2.0 * w_lev_ant
            neck_z_deg += -2.5 * w_lev_ant

            w_paw_lift = _window_bell(f, lvs + 4.0, lvs + 10.0, lvs + 18.0, lvs + 26.0)
            torso_dx += -0.003 * w_paw_lift
            chest_dx += -0.002 * w_paw_lift
            torso_ry_deg += 1.2 * w_paw_lift
            shR_dz += 0.006 * w_paw_lift

            w_lev_push = _window_bell(f, lvs + 21.0, lvs + 28.0, lvs + 48.0, lvs + 60.0)
            torso_dy += -0.008 * w_lev_push
            torso_dz += -0.005 * w_lev_push
            chest_dy += -0.005 * w_lev_push
            chest_dz += -0.004 * w_lev_push
            chest_x_deg += 3.0 * w_lev_push
            chest_z_deg += -1.5 * w_lev_push
            torso_rx_deg += 1.5 * w_lev_push
            shL_dy += -0.006 * w_lev_push
            shL_dz += -0.004 * w_lev_push
            shL_rx += math.radians(4.0) * w_lev_push

        blink_w_L = 0.0
        blink_w_R = 0.0
        for _, bf_start, bf_dur, bf_peak in blink_events_scheduled:
            blink_w_L = max(blink_w_L, _blink_pulse(f, bf_start, duration=bf_dur, close_frames=2.0, peak=bf_peak))
            blink_w_R = max(blink_w_R, _blink_pulse(f, bf_start + 0.4, duration=bf_dur, close_frames=2.0, peak=bf_peak))

        if lick_clip:
            w_half1 = 0.76 * _window_bell(f, ls + 16.0, ls + 21.0, ls + 35.0, ls + 41.0)
            w_half2 = 0.80 * _window_bell(f, ls + 46.0, ls + 51.0, ls + 65.0, ls + 71.0)
            blink_w_L = max(blink_w_L, w_half1, w_half2)
            blink_w_R = max(blink_w_R, w_half1 * 0.95, w_half2 * 0.95)

        for lid_bone, closed_vec in EYELID_CLOSED_LOCATIONS.items():
            if lid_bone in loc_tracks:
                w_eye = blink_w_L if ".L" in lid_bone else blink_w_R
                loc_tracks[lid_bone].append((
                    closed_vec[0] * w_eye,
                    closed_vec[1] * w_eye,
                    closed_vec[2] * w_eye,
                ))

        earL_x_deg, earL_z_deg = 0.0, 0.0
        earR_x_deg, earR_z_deg = 0.0, 0.0

        if jump_clip:
            w_ear_jmp = _window_bell(f, js - 13.0, js - 8.0, js + 2.0, js + 8.0)
            earL_x_deg += -11.0 * w_ear_jmp
            earL_z_deg += 6.0 * w_ear_jmp
            earR_x_deg += -12.5 * _window_bell(f, js - 15.0, js - 10.0, js + 1.0, js + 7.0)
            earR_z_deg += -5.5 * w_ear_jmp

        if sit_clip:
            w_ear_sit = _window_bell(f, sit_e + 6.0, sit_e + 9.0, sit_e + 15.0, sit_e + 20.0)
            earL_x_deg += 8.5 * w_ear_sit
            earL_z_deg += -15.0 * w_ear_sit

        if lick_clip:
            w_ear_l1 = _window_bell(f, ls + 18.0, ls + 23.0, ls + 38.0, ls + 44.0)
            earL_x_deg += 7.0 * w_ear_l1
            earR_z_deg += 12.0 * w_ear_l1
            w_ear_l2 = _window_bell(f, ls + 54.0, ls + 57.0, ls + 62.0, ls + 67.0)
            earR_x_deg += -10.5 * w_ear_l2
            earR_z_deg += -16.0 * w_ear_l2

        if look_clip:
            w_ear_w1 = _window_bell(f, ws + 20.0, ws + 24.0, ws + 33.0, ws + 39.0)
            earR_x_deg += -12.0 * w_ear_w1
            earR_z_deg += 19.0 * w_ear_w1
            w_ear_w2 = _window_bell(f, ws + 66.0, ws + 70.0, ws + 79.0, ws + 86.0)
            earL_x_deg += -9.0 * w_ear_w2
            earL_z_deg += 16.0 * w_ear_w2
            earR_z_deg += 11.0 * w_ear_w2

        breath_amp = 0.65 if walk_env < 0.2 else 0.25
        breath_wave = breath_amp * math.sin(2.0 * math.pi * (f - start_f) / 38.0)
        chest_dz += 0.0038 * breath_wave
        chest_x_deg += -1.9 * breath_wave

        if "torso" in loc_tracks:
            loc_tracks["torso"].append((torso_dx, torso_dy, torso_dz))
        if "chest" in loc_tracks:
            loc_tracks["chest"].append((chest_dx, chest_dy, chest_dz))
        if "shoulder.L" in loc_tracks:
            loc_tracks["shoulder.L"].append((shL_dx, shL_dy, shL_dz))
        if "shoulder.R" in loc_tracks:
            loc_tracks["shoulder.R"].append((shR_dx, shR_dy, shR_dz))

        if "shoulder.L" in euler_tracks:
            euler_tracks["shoulder.L"].append((shL_rx, shL_ry, shL_rz))
        if "shoulder.R" in euler_tracks:
            euler_tracks["shoulder.R"].append((shR_rx, shR_ry, shR_rz))

        rot_deg_map = {
            "torso": (torso_rx_deg, torso_ry_deg, torso_rz_deg),
            "hips": (0.0, 0.0, hips_z_deg),
            "chest": (chest_x_deg, chest_y_deg, chest_z_deg),
            "spine_fk": (0.0, 0.0, sp0_z_deg),
            "spine_fk.001": (0.0, 0.0, sp1_z_deg),
            "spine_fk.002": (0.0, 0.0, sp2_z_deg),
            "spine_fk.003": (0.0, 0.0, sp3_z_deg),
            "neck": (neck_x_deg, neck_y_deg, neck_z_deg),
            "head": (head_x_deg, head_y_deg, head_z_deg),
            "ear.L": (earL_x_deg, 0.0, earL_z_deg),
            "ear.R": (earR_x_deg, 0.0, earR_z_deg),
            "tail_master.001": (tail_x_deg, 0.0, tail_z_deg),
        }
        for bname, (rx_d, ry_d, rz_d) in rot_deg_map.items():
            if bname in quat_tracks:
                q = Euler((math.radians(rx_d), math.radians(ry_d), math.radians(rz_d)), "XYZ").to_quaternion()
                quat_tracks[bname].append((float(q[0]), float(q[1]), float(q[2]), float(q[3])))

    def _write_vec_fcurves(bname: str, prop: str, samples: list, dim: int):
        dp = f'pose.bones["{bname}"].{prop}'
        for axis in range(dim):
            fc = fcs.find(dp, index=axis)
            if fc is None:
                fc = fcs.new(data_path=dp, index=axis)
            fc.keyframe_points.add(total_frames)
            for idx, tup in enumerate(samples):
                kp = fc.keyframe_points[idx]
                kp.co = (float(start_f + idx), float(tup[axis]))
                kp.interpolation = "LINEAR"
            fc.update()

    for bname, samples in loc_tracks.items():
        _write_vec_fcurves(bname, "location", samples, 3)
    for bname, samples in euler_tracks.items():
        _write_vec_fcurves(bname, "rotation_euler", samples, 3)
    for bname, samples in quat_tracks.items():
        _write_vec_fcurves(bname, "rotation_quaternion", samples, 4)

    bio_track = adt.nla_tracks.new()
    bio_track.name = STRAY_BIOMECH_TRACK_NAME
    bio_strip = bio_track.strips.new(bio_act.name, start_f, bio_act)
    bind_action_slot(bio_strip, bio_act)
    bio_strip.blend_type = "COMBINE"
    bio_strip.extrapolation = "HOLD"
    bio_strip.use_auto_blend = False
    bio_strip.blend_in = 0.0
    bio_strip.blend_out = 0.0
    bio_strip.scale = 1.0
    bio_strip.repeat = 1.0
    bio_strip.action_frame_start = float(start_f)
    bio_strip.action_frame_end = float(end_f)
    bio_strip.frame_start = float(start_f)
    bio_strip.frame_end = float(end_f)

    if saved_add:
        _append_additive_track_on_top(adt, saved_add)

    ctrl_obj["cat_stray_biomech_baked"] = True
    ctrl_obj["cat_stray_biomech_frames"] = total_frames
    return {
        "ok": True,
        "track": bio_track.name,
        "action": bio_act.name,
        "frame_range": [start_f, end_f],
        "fcurves_count": len(fcs),
        "blink_events": len(blink_events_scheduled) + (2 if lick_clip else 0),
    }
