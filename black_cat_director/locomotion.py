# -*- coding: utf-8 -*-
"""
Black Cat Animation Director Studio v2.0 — 3D Curve Locomotion & Zero-Slip Solver
=================================================================================
Computes exact 3D arc-length tables for Bezier/Poly curves, synchronizes quadruped
stride speed (`0.32 m/s` Walk, `0.78 m/s` Slow Run, `1.35 m/s` Fast Run) with the
cat's scale and playback speed so paws NEVER slip on the ground, keeps the body
level (`X=0, Y=0`) while `Z` yaw follows the horizontal curve tangent + per-point
Bezier `Tilt` (`bp.tilt`), and synchronizes vertical climbs (`Z0 -> Z1`) with
the airborne frames of `Cat _Jump  (1_27)`.
"""

import json
import math
import bpy
from mathutils import Vector

from .constants import (
    CAT_ACTION_CATALOG,
    DEFAULT_CIRCLE_CURVE_POINTS,
    DEFAULT_LEDGE_JUMP_CURVE_POINTS,
    DEFAULT_S_CURVE_POINTS,
    DEFAULT_WALK_ACTION,
    PATHS_COLLECTION_NAME,
    bind_action_slot,
    ensure_collection,
    get_action_fcurves,
    resolve_action_name,
)
from .rig_actors import find_cat_controller


# ============================================================================
# 1. BIOMECHANICAL STRIDE SPEED & ROLE HELPERS
# ============================================================================

def get_cat_exact_stride_speed(ctrl_obj, action_obj, speed_mult_override: float = None) -> float:
    """
    Returns calibrated world-space locomotion speed (m/s) for `action_obj`,
    scaled by the cat controller's character scale and strip playback speed.
    Stationary actions (`Idle`, `Seated`, `Paw Lick`, `Paw Reach`, `Sleep`) return `0.0 m/s`.
    """
    if not action_obj:
        return 0.0
    act_name = resolve_action_name(action_obj.name)
    meta = CAT_ACTION_CATALOG.get(act_name, {})
    base_v = float(action_obj.get("cat_speed_mps", meta.get("speed_mps", 0.0)))
    if base_v <= 0.01:
        return 0.0

    char_scale = 1.0
    anim_speed = 1.0
    if ctrl_obj:
        char_scale = max(0.1, float(ctrl_obj.get("cat_char_scale", ctrl_obj.scale.x)))
        anim_speed = max(0.1, float(ctrl_obj.get("cat_anim_speed", 1.0)))
    if speed_mult_override is not None:
        anim_speed = max(0.1, float(speed_mult_override))

    return base_v * char_scale * anim_speed


def is_default_fill_cat_locomotion(action_obj) -> bool:
    """True for continuous walking/running cycles that stretch to fill curve arc-length."""
    if not action_obj:
        return False
    act_name = resolve_action_name(action_obj.name)
    meta = CAT_ACTION_CATALOG.get(act_name, {})
    role = action_obj.get("cat_role", meta.get("default_role", "FIXED"))
    if role == "FILL":
        return True
    low = act_name.lower()
    return ("walk" in low or "run" in low) and ("jump" not in low)


# ============================================================================
# 2. 3D BEZIER ARC-LENGTH SAMPLER WITH TILT & LEDGE-HOP DETECTOR
# ============================================================================

def _eval_cubic_bezier(p0: Vector, p1: Vector, p2: Vector, p3: Vector, t: float) -> Vector:
    u = 1.0 - t
    return (
        (u * u * u) * p0
        + (3.0 * u * u * t) * p1
        + (3.0 * u * t * t) * p2
        + (t * t * t) * p3
    )


def sample_curve_arclength_table_3d(curve_obj, samples_per_seg: int = 64) -> dict:
    """
    Samples a 3D Curve in world space into a high-resolution arc-length table:
      - `pts`: list of world-space `Vector` samples
      - `tilts`: list of interpolated Bezier point `tilt` angles (in radians)
      - `cum_s`: cumulative 3D arc-length (meters)
      - `cum_xy`: cumulative horizontal 2D XY distance (meters)
      - `total_len`: total 3D curve length (meters)
      - `has_hop`: True if the curve contains a steep vertical ledge jump (`|dz| > 0.12m`)
    Supports both Bezier and Poly/NURBS splines (automatically picks the longest active spline).
    """
    if not curve_obj or curve_obj.type != "CURVE" or not curve_obj.data.splines:
        p0 = Vector((0.0, 0.0, 0.0))
        p1 = Vector((0.0, -1.0, 0.0))
        return {
            "pts": [p0, p1],
            "tilts": [0.0, 0.0],
            "cum_s": [0.0, 1.0],
            "cum_xy": [0.0, 1.0],
            "total_len": 1.0,
            "total_xy_len": 1.0,
            "has_hop": False,
            "u_hop_start": 0.0,
            "u_hop_end": 0.0,
            "s_before_hop": 1.0,
            "s_after_hop": 0.0,
            "z_start": 0.0,
            "z_end": 0.0,
        }

    mw = curve_obj.matrix_world
    # Pick the spline with the most control points (handles drawn strokes cleanly)
    best_sp = None
    best_count = -1
    for sp_cand in curve_obj.data.splines:
        cnt = len(sp_cand.bezier_points) if sp_cand.type == "BEZIER" else len(sp_cand.points)
        if cnt > best_count:
            best_count = cnt
            best_sp = sp_cand

    sp = best_sp
    pts = []
    tilts = []

    if sp.type == "BEZIER":
        bpts = sp.bezier_points
        n_bp = len(bpts)
        if n_bp < 2:
            p0 = mw @ bpts[0].co if n_bp == 1 else mw.translation.copy()
            p1 = p0 + Vector((0.0, -1.0, 0.0))
            return {
                "pts": [p0, p1],
                "tilts": [0.0, 0.0],
                "cum_s": [0.0, 1.0],
                "cum_xy": [0.0, 1.0],
                "total_len": 1.0,
                "total_xy_len": 1.0,
                "has_hop": False,
                "u_hop_start": 0.0,
                "u_hop_end": 0.0,
                "s_before_hop": 1.0,
                "s_after_hop": 0.0,
                "z_start": float(p0.z),
                "z_end": float(p0.z),
            }

        seg_count = n_bp if sp.use_cyclic_u else (n_bp - 1)
        for seg_idx in range(seg_count):
            bp0 = bpts[seg_idx]
            bp1 = bpts[(seg_idx + 1) % n_bp]
            p0 = mw @ bp0.co
            p1 = mw @ bp0.handle_right
            p2 = mw @ bp1.handle_left
            p3 = mw @ bp1.co
            t0 = float(getattr(bp0, "tilt", 0.0))
            t1 = float(getattr(bp1, "tilt", 0.0))

            for s in range(samples_per_seg):
                if seg_idx > 0 and s == 0:
                    continue
                t = float(s) / float(samples_per_seg)
                pts.append(_eval_cubic_bezier(p0, p1, p2, p3, t))
                ts = t * t * (3.0 - 2.0 * t)
                tilts.append(t0 + (t1 - t0) * ts)
        pts.append(mw @ bpts[0 if sp.use_cyclic_u else -1].co)
        tilts.append(float(getattr(bpts[0 if sp.use_cyclic_u else -1], "tilt", 0.0)))
    else:
        # POLY or NURBS spline
        spts = sp.points
        n_sp = len(spts)
        if n_sp < 2:
            p0 = mw @ Vector(spts[0].co[:3]) if n_sp == 1 else mw.translation.copy()
            p1 = p0 + Vector((0.0, -1.0, 0.0))
            pts = [p0, p1]
            tilts = [0.0, 0.0]
        else:
            seg_count = n_sp if sp.use_cyclic_u else (n_sp - 1)
            for seg_idx in range(seg_count):
                sp0 = spts[seg_idx]
                sp1 = spts[(seg_idx + 1) % n_sp]
                p0 = mw @ Vector(sp0.co[:3])
                p1 = mw @ Vector(sp1.co[:3])
                t0 = float(getattr(sp0, "tilt", 0.0))
                t1 = float(getattr(sp1, "tilt", 0.0))
                sub = max(8, samples_per_seg // 4)
                for s in range(sub):
                    if seg_idx > 0 and s == 0:
                        continue
                    t = float(s) / float(sub)
                    pts.append(p0.lerp(p1, t))
                    tilts.append(t0 + (t1 - t0) * t)
            pts.append(mw @ Vector(spts[0 if sp.use_cyclic_u else -1].co[:3]))
            tilts.append(float(getattr(spts[0 if sp.use_cyclic_u else -1], "tilt", 0.0)))

    cum_s = [0.0]
    cum_xy = [0.0]
    for i in range(1, len(pts)):
        d3 = (pts[i] - pts[i - 1]).length
        d2 = math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y)
        cum_s.append(cum_s[-1] + d3)
        cum_xy.append(cum_xy[-1] + d2)

    total_len = max(1e-4, cum_s[-1])
    total_xy_len = max(1e-4, cum_xy[-1])
    curve_obj["cat_cached_arc_len"] = round(total_len, 4)

    z0 = float(pts[0].z)
    z1 = float(pts[-1].z)
    dz_total = z1 - z0
    has_hop = abs(dz_total) > 0.12

    u_hop_start = 0.0
    u_hop_end = 0.0
    s_before_hop = total_len
    s_after_hop = 0.0

    if has_hop:
        z_low = min(z0, z1)
        z_high = max(z0, z1)
        span_z = max(1e-4, z_high - z_low)
        idx_start = 0
        idx_end = len(pts) - 1
        if dz_total > 0:
            for i, p in enumerate(pts):
                if (p.z - z0) / span_z < 0.06:
                    idx_start = i
                if (p.z - z0) / span_z <= 0.94:
                    idx_end = i
        else:
            for i, p in enumerate(pts):
                if (z0 - p.z) / span_z < 0.06:
                    idx_start = i
                if (z0 - p.z) / span_z <= 0.94:
                    idx_end = i

        idx_start = max(0, idx_start - 2)
        idx_end = min(len(pts) - 1, max(idx_start + 4, idx_end + 2))
        s_before_hop = cum_s[idx_start]
        s_hop_end = cum_s[idx_end]
        s_after_hop = max(0.0, total_len - s_hop_end)
        u_hop_start = s_before_hop / total_len
        u_hop_end = s_hop_end / total_len

    return {
        "pts": pts,
        "tilts": tilts,
        "cum_s": cum_s,
        "cum_xy": cum_xy,
        "total_len": total_len,
        "total_xy_len": total_xy_len,
        "has_hop": has_hop,
        "u_hop_start": u_hop_start,
        "u_hop_end": u_hop_end,
        "s_before_hop": s_before_hop,
        "s_after_hop": s_after_hop,
        "z_start": z0,
        "z_end": z1,
        "is_cyclic": bool(sp.use_cyclic_u),
    }


def compute_curve_true_1d_length(curve_obj) -> float:
    if not curve_obj or curve_obj.type != "CURVE":
        return 1.85
    cached = float(curve_obj.get("cat_cached_arc_len", 0.0))
    try:
        tbl = sample_curve_arclength_table_3d(curve_obj)
        return tbl["total_len"]
    except Exception:
        return cached if cached > 0.1 else 1.85


def query_curve_table_at_u(tbl: dict, u: float, flip_forward: bool = False) -> tuple:
    """
    Queries `(pos_vec, yaw_rad)` at normalized arc-length `u in [0.0, 1.0]`.
    Since the cat rig faces `-Y` in local space:
      forward vector `(dx, dy)` in world XY corresponds to `tangent_yaw = atan2(dx, -dy)`.
      Any per-point Bezier `tilt` (`bp.tilt`) is added directly to `tangent_yaw`.
    """
    pts = tbl["pts"]
    tilts = tbl.get("tilts") or ([0.0] * len(pts))
    cum_s = tbl["cum_s"]
    total_len = tbl["total_len"]
    u = max(0.0, min(1.0, float(u)))
    target_s = u * total_len

    idx = 0
    while idx < len(cum_s) - 2 and cum_s[idx + 1] < target_s:
        idx += 1

    seg_len = max(1e-6, cum_s[idx + 1] - cum_s[idx])
    t = max(0.0, min(1.0, (target_s - cum_s[idx]) / seg_len))
    pos = pts[idx].lerp(pts[idx + 1], t)
    tilt_rad = tilts[idx] + (tilts[idx + 1] - tilts[idx]) * t

    def _pt_at_s(s_val):
        j = 0
        while j < len(cum_s) - 2 and cum_s[j + 1] < s_val:
            j += 1
        sl = max(1e-6, cum_s[j + 1] - cum_s[j])
        tt = max(0.0, min(1.0, (s_val - cum_s[j]) / sl))
        return pts[j].lerp(pts[j + 1], tt)

    win = 0.06
    p_b = _pt_at_s(max(0.0, target_s - win))
    p_a = _pt_at_s(min(total_len, target_s + win))
    tang = p_a - p_b
    dx, dy, dz = float(tang.x), float(tang.y), float(tang.z)

    if tbl.get("has_hop") and u <= float(tbl.get("u_hop_end", 0.45)) + 0.05:
        s_hop_s = max(0.0, float(tbl.get("u_hop_start", 0.05)) * total_len - 0.10)
        s_hop_e = min(total_len, (float(tbl.get("u_hop_end", 0.45)) + 0.06) * total_len)
        hop_chord = _pt_at_s(s_hop_e) - _pt_at_s(s_hop_s)
        if math.hypot(hop_chord.x, hop_chord.y) > 0.05:
            u_he = float(tbl.get("u_hop_end", 0.45))
            if u <= u_he:
                dx, dy = float(hop_chord.x), float(hop_chord.y)
            else:
                w_post = max(0.0, min(1.0, (u - u_he) / 0.05))
                dx = (1.0 - w_post) * float(hop_chord.x) + w_post * dx
                dy = (1.0 - w_post) * float(hop_chord.y) + w_post * dy
    elif math.hypot(dx, dy) < 0.03 or abs(dz) > 0.85 * math.hypot(dx, dy):
        p_b2 = _pt_at_s(max(0.0, target_s - 0.35))
        p_a2 = _pt_at_s(min(total_len, target_s + 0.35))
        t2 = p_a2 - p_b2
        dx, dy = float(t2.x), float(t2.y)

    if flip_forward:
        dx, dy = -dx, -dy

    if math.hypot(dx, dy) < 1e-5:
        yaw_rad = tilt_rad
    else:
        yaw_rad = math.atan2(dx, -dy) + tilt_rad

    return pos, yaw_rad


# ============================================================================
# 3. 3D CURVE BUILDER & PRESET SHAPES
# ============================================================================

def create_cat_walk_curve(
    name: str = "Cat_Path_01",
    points=None,
    cyclic: bool = False,
    bevel_depth: float = 0.008,
    preset_shape: str = "S_CURVE",
):
    """Creates or updates a 3D Bezier curve in `02_CAT_LOCOMOTION_CURVES`."""
    if not points or len(points) < 2:
        existing = bpy.data.objects.get(name)
        if (
            existing
            and existing.type == "CURVE"
            and existing.data.splines
            and len(existing.data.splines[0].bezier_points) >= 2
            and not preset_shape
        ):
            sample_curve_arclength_table_3d(existing)
            return existing
        if preset_shape == "LEDGE_JUMP":
            points = list(DEFAULT_LEDGE_JUMP_CURVE_POINTS)
        elif preset_shape == "CIRCLE":
            points = list(DEFAULT_CIRCLE_CURVE_POINTS)
            cyclic = True
        else:
            points = list(DEFAULT_S_CURVE_POINTS)

    paths_col = ensure_collection(PATHS_COLLECTION_NAME)
    existing = bpy.data.objects.get(name)
    if existing and existing.type == "CURVE":
        cobj = existing
        cdata = cobj.data
        cdata.splines.clear()
    else:
        cdata = bpy.data.curves.new(name=name, type="CURVE")
        cobj = bpy.data.objects.new(name, cdata)
        paths_col.objects.link(cobj)
    cobj.location = (0.0, 0.0, 0.0)
    cobj.rotation_euler = (0.0, 0.0, 0.0)
    cobj.scale = (1.0, 1.0, 1.0)

    cdata.dimensions = "3D"
    cdata.resolution_u = 48
    cdata.bevel_depth = float(bevel_depth)

    sp = cdata.splines.new(type="BEZIER")
    sp.use_cyclic_u = bool(cyclic)
    sp.bezier_points.add(len(points) - 1)
    for i, pt in enumerate(points):
        bp = sp.bezier_points[i]
        bp.co = Vector(pt)
        bp.handle_left_type = "AUTO"
        bp.handle_right_type = "AUTO"
    sp.resolution_u = 48

    cobj.hide_render = True
    mat_name = "CAT_Curve_Path_Mat"
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(name=mat_name)
        mat.use_nodes = True
        if mat.node_tree:
            bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if bsdf and "Base Color" in bsdf.inputs:
                bsdf.inputs["Base Color"].default_value = (0.15, 0.82, 1.0, 1.0)
    if len(cdata.materials) == 0:
        cdata.materials.append(mat)

    sample_curve_arclength_table_3d(cobj)
    return cobj


# ============================================================================
# 4. ZERO-SLIP NLA CURVE TIMING SOLVER
# ============================================================================

def solve_cat_nla_curve_timing_plan(ctrl_obj, clip_specs: list, curve_obj=None, fps: float = None) -> dict:
    """
    Solves the exact per-clip repeat counts, frame intervals, and frame-by-frame curve
    progression `u_hat_per_frame` plus jump elevation windows `[jump_air_start, jump_air_end]`
    for a multi-clip NLA sequence on a Black Cat actor:
      - Stationary clips (`Idle`, `Sit`, `Paw Lick`, `Sleep`, etc.) have `speed_mps = 0.0`,
        holding the cat's exact curve position with zero drift.
      - Locomotion clips (`Cat_Walk`, `Cat_ slow Run`, `Cat _Run`, `Cat _Jump`) advance along
        the curve at their exact biomechanical stride speed (`speed_mps * scale * playback_speed`)
        so paws NEVER drag or slide!
      - If a locomotion clip is in `FILL` (or `AUTO`) mode, its `effective_repeat` is automatically
        calculated so the walk covers the remaining curve length at exact zero-slip stride speed.
      - If all locomotion clips are in `FIXED` mode (explicit user repeat counts), each clip
        advances along the curve by its exact physical distance `s_cum[tau] / arc_len` at exact
        zero-slip stride speed!
    """
    if fps is None:
        try:
            scn = bpy.context.scene
            fps = float(scn.render.fps) / max(1e-4, float(scn.render.fps_base))
        except Exception:
            fps = 24.0
    fps = max(1.0, float(fps))

    if curve_obj is None and ctrl_obj:
        cname = ctrl_obj.get("cat_attached_curve", "")
        if cname:
            curve_obj = bpy.data.objects.get(cname)

    tbl = sample_curve_arclength_table_3d(curve_obj) if (curve_obj and curve_obj.type == "CURVE") else None
    arc_len = tbl["total_len"] if tbl else 0.0
    default_spd_mult = float(ctrl_obj.get("cat_anim_speed", 1.0)) if ctrl_obj else 1.0

    raw_clips = []
    for idx, spec in enumerate(clip_specs or []):
        if isinstance(spec, str):
            act_name = spec
            user_rep = 1.0
            spd_mult = default_spd_mult
            bld = 0 if idx == 0 else 8
            mode = "AUTO"
        elif isinstance(spec, dict):
            act_name = spec.get("action") or spec.get("action_name") or spec.get("name") or ""
            user_rep = float(spec.get("repeat", 1.0))
            spd_mult = float(spec.get("speed", default_spd_mult))
            bld = int(round(float(spec.get("blend", spec.get("blend_in", 0 if idx == 0 else 8)))))
            mode = str(spec.get("mode", "AUTO")).upper()
        else:
            continue

        act_name = resolve_action_name(act_name)
        act = bpy.data.actions.get(act_name)
        if not act:
            continue

        f0_span = max(1.0, float(act.frame_range[1] - act.frame_range[0]))
        spd_mult = max(0.1, round(spd_mult, 3))
        v_mps = get_cat_exact_stride_speed(ctrl_obj, act, speed_mult_override=spd_mult)
        t_single_sec = f0_span / (fps * spd_mult)
        dist_single_m = v_mps * t_single_sec

        if mode == "FILL" and dist_single_m > 0.03:
            is_fill = True
        elif mode == "FIXED" or dist_single_m <= 0.03:
            is_fill = False
        else:
            mode = "AUTO"
            is_fill = is_default_fill_cat_locomotion(act)

        raw_clips.append({
            "index": len(raw_clips),
            "action": act.name,
            "act_obj": act,
            "f0_span": f0_span,
            "user_repeat": max(0.05, round(user_rep, 2)),
            "speed": spd_mult,
            "blend": 0 if len(raw_clips) == 0 else max(0, bld),
            "mode": mode,
            "is_fill": is_fill,
            "speed_mps": v_mps,
            "t_single_sec": t_single_sec,
            "dist_single_m": dist_single_m,
            "is_jump": ("jump" in act.name.lower()),
        })

    if not raw_clips:
        return {
            "clips": [],
            "cycle_frames": 100,
            "arc_len_m": arc_len,
            "total_distance_m": 0.0,
            "u_hat_per_frame": [0.0, 1.0],
            "jump_windows": [],
        }

    jump_indices = [i for i, c in enumerate(raw_clips) if c["is_jump"]]
    has_curve_hop = bool(tbl and tbl.get("has_hop") and len(jump_indices) > 0)
    fill_indices = [i for i, c in enumerate(raw_clips) if c["is_fill"] and c["dist_single_m"] > 0.03]

    if has_curve_hop:
        j_idx = jump_indices[0]
        s_before = float(tbl["s_before_hop"])
        s_after = float(tbl["s_after_hop"])

        pre_fill = [i for i in range(0, j_idx) if raw_clips[i]["is_fill"] and raw_clips[i]["dist_single_m"] > 0.03]
        post_fill = [i for i in range(j_idx + 1, len(raw_clips)) if raw_clips[i]["is_fill"] and raw_clips[i]["dist_single_m"] > 0.03]

        for i, c in enumerate(raw_clips):
            c["effective_repeat"] = c["user_repeat"]

        if pre_fill:
            w_sum = sum(max(0.1, raw_clips[i]["user_repeat"]) for i in pre_fill)
            for i in pre_fill:
                alloc_m = s_before * (max(0.1, raw_clips[i]["user_repeat"]) / max(1e-6, w_sum))
                raw_clips[i]["effective_repeat"] = max(0.30, alloc_m / max(0.03, raw_clips[i]["dist_single_m"]))

        if post_fill:
            w_sum = sum(max(0.1, raw_clips[i]["user_repeat"]) for i in post_fill)
            for i in post_fill:
                alloc_m = s_after * (max(0.1, raw_clips[i]["user_repeat"]) / max(1e-6, w_sum))
                raw_clips[i]["effective_repeat"] = max(0.30, alloc_m / max(0.03, raw_clips[i]["dist_single_m"]))
    else:
        fixed_indices = [i for i in range(len(raw_clips)) if i not in fill_indices]

        if arc_len > 0.2 and fill_indices:
            dist_fixed_sum = sum(raw_clips[i]["user_repeat"] * raw_clips[i]["dist_single_m"] for i in fixed_indices)
            blend_overlap_dist = 0.0
            for i in range(1, len(raw_clips)):
                b_sec = float(raw_clips[i]["blend"]) / fps
                v_avg = 0.5 * (raw_clips[i - 1]["speed_mps"] + raw_clips[i]["speed_mps"])
                blend_overlap_dist += v_avg * b_sec

            fill_needed_m = max(0.25, arc_len - dist_fixed_sum + blend_overlap_dist)
            total_weight = sum(max(0.1, raw_clips[j]["user_repeat"]) for j in fill_indices)
            for j in fill_indices:
                w_j = max(0.1, raw_clips[j]["user_repeat"])
                alloc_dist_m = fill_needed_m * (w_j / max(1e-6, total_weight))
                eff_rep = alloc_dist_m / max(0.03, raw_clips[j]["dist_single_m"])
                raw_clips[j]["effective_repeat"] = max(0.30, eff_rep)
            for i in fixed_indices:
                raw_clips[i]["effective_repeat"] = raw_clips[i]["user_repeat"]
        else:
            for c in raw_clips:
                c["effective_repeat"] = c["user_repeat"]

    tau_cursor = 0
    jump_windows = []
    for i, c in enumerate(raw_clips):
        single_frames = max(1.0, c["f0_span"] / c["speed"])
        df = max(4, int(round(c["effective_repeat"] * single_frames)))
        c["duration_frames"] = df
        c["effective_repeat"] = round(float(df) / single_frames, 4)
        if i == 0:
            c["eff_blend"] = 0
            c["tau_start"] = 0
            c["tau_end"] = df
        else:
            prev_df = raw_clips[i - 1]["duration_frames"]
            max_b = max(0, min(int(prev_df * 0.40), int(df * 0.40)))
            eff_b = min(int(c["blend"]), max_b)
            c["eff_blend"] = eff_b
            c["tau_start"] = max(0, tau_cursor - eff_b)
            c["tau_end"] = c["tau_start"] + df
        tau_cursor = c["tau_end"]

        if c["is_jump"]:
            air_s = c["tau_start"] + int(round(df * (5.0 / 27.0)))
            air_e = c["tau_start"] + int(round(df * (21.0 / 27.0)))
            jump_windows.append({
                "clip_index": i,
                "tau_start": c["tau_start"],
                "tau_end": c["tau_end"],
                "air_start": air_s,
                "air_end": max(air_s + 2, air_e),
            })

    cycle_frames = max(4, tau_cursor)

    if has_curve_hop and jump_windows:
        jw = jump_windows[0]
        j_idx = jw["clip_index"]
        u_hs = float(tbl["u_hop_start"])
        u_he = float(tbl["u_hop_end"])
        air_s = jw["air_start"]
        air_e = jw["air_end"]

        pre_s = [0.0] * (air_s + 1)
        for tau in range(1, air_s + 1):
            v_tau = 0.0
            for i in range(0, j_idx):
                c = raw_clips[i]
                if c["tau_start"] <= tau <= c["tau_end"] and c["speed_mps"] > 0.01:
                    v_tau = max(v_tau, c["speed_mps"])
            pre_s[tau] = pre_s[tau - 1] + (v_tau / fps)
        pre_tot = pre_s[-1]

        post_len = max(1, cycle_frames - air_e)
        post_s = [0.0] * (post_len + 1)
        for k in range(1, post_len + 1):
            tau = air_e + k
            v_tau = 0.0
            for i in range(j_idx + 1, len(raw_clips)):
                c = raw_clips[i]
                if c["tau_start"] <= tau <= c["tau_end"] and c["speed_mps"] > 0.01:
                    if not c["is_jump"]:
                        v_tau = max(v_tau, c["speed_mps"])
            post_s[k] = post_s[k - 1] + (v_tau / fps)
        post_tot = post_s[-1]

        u_hat = [0.0] * (cycle_frames + 1)
        for tau in range(cycle_frames + 1):
            if tau <= air_s:
                if pre_tot > 1e-5:
                    u_hat[tau] = u_hs * (pre_s[tau] / pre_tot)
                else:
                    u_hat[tau] = u_hs * (float(tau) / max(1.0, float(air_s)))
            elif tau <= air_e:
                u_air = float(tau - air_s) / float(max(1, air_e - air_s))
                u_smooth = u_air * u_air * (3.0 - 2.0 * u_air)
                u_hat[tau] = u_hs + (u_he - u_hs) * u_smooth
            else:
                k = tau - air_e
                if post_tot > 1e-5:
                    u_hat[tau] = u_he + (1.0 - u_he) * (post_s[k] / post_tot)
                else:
                    u_hat[tau] = u_he + (1.0 - u_he) * (float(k) / float(post_len))
        total_dist_m = arc_len
    else:
        def _clip_inst_speed(c, tau):
            base_v = c["speed_mps"]
            if not c["is_jump"] or base_v <= 0.01:
                return base_v
            df = max(1, c["duration_frames"])
            rel = float(tau - c["tau_start"]) / float(df)
            if rel < 0.18 or rel > 0.78:
                return base_v * 0.05
            u_air = (rel - 0.18) / 0.60
            bell = math.sin(math.pi * u_air)
            return base_v * 2.55 * bell

        v_net = [0.0] * (cycle_frames + 1)
        for tau in range(cycle_frames + 1):
            v_val = _clip_inst_speed(raw_clips[0], tau) if tau <= raw_clips[0]["tau_end"] else 0.0
            for i in range(1, len(raw_clips)):
                c = raw_clips[i]
                ts = c["tau_start"]
                te = c["tau_end"]
                eb = c["eff_blend"]
                if tau >= ts:
                    c_spd = _clip_inst_speed(c, tau) if tau <= te else 0.0
                    if eb > 0 and tau < ts + eb:
                        alpha = float(tau - ts) / float(eb)
                    else:
                        alpha = 1.0
                    v_val = (1.0 - alpha) * v_val + alpha * c_spd
            v_net[tau] = max(0.0, v_val)

        s_cum = [0.0] * (cycle_frames + 1)
        for tau in range(1, cycle_frames + 1):
            v_mid = 0.5 * (v_net[tau - 1] + v_net[tau])
            s_cum[tau] = s_cum[tau - 1] + (v_mid / fps)

        total_dist_m = s_cum[-1]
        if total_dist_m > 1e-5:
            if fill_indices and arc_len > 0.2:
                # FILL mode: effective_repeat was solved so total_dist_m matches arc_len
                u_hat = [s / total_dist_m for s in s_cum]
                u_hat[0] = 0.0
                u_hat[-1] = 1.0
            elif arc_len > 0.05:
                # FIXED mode: advance by exact physical stride distance s_cum[tau] along the curve!
                u_hat = [s / arc_len for s in s_cum]
            else:
                u_hat = [s / total_dist_m for s in s_cum]
        else:
            u_hat = [0.0 for _ in range(cycle_frames + 1)]

    plan_clips = []
    for c in raw_clips:
        ts = min(cycle_frames, max(0, c["tau_start"]))
        te = min(cycle_frames, max(0, c["tau_end"]))
        tm = min(cycle_frames, max(0, (ts + te) // 2))
        plan_clips.append({
            "index": c["index"],
            "action": c["action"],
            "repeat": c["user_repeat"],
            "effective_repeat": c["effective_repeat"],
            "speed": c["speed"],
            "blend": c["blend"],
            "eff_blend": c["eff_blend"],
            "mode": c["mode"],
            "is_fill": c["is_fill"],
            "speed_mps": round(c["speed_mps"], 2),
            "tau_start": ts,
            "tau_end": te,
            "duration_frames": c["duration_frames"],
            "u_start_pct": round(100.0 * min(1.0, u_hat[ts]), 1),
            "u_end_pct": round(100.0 * min(1.0, u_hat[te]), 1),
            "u_mid_pct": round(100.0 * min(1.0, u_hat[tm]), 1),
            "dist_m": round((u_hat[te] - u_hat[ts]) * arc_len, 2),
        })

    return {
        "clips": plan_clips,
        "cycle_frames": cycle_frames,
        "arc_len_m": round(arc_len, 3),
        "total_distance_m": round(total_dist_m, 3),
        "u_hat_per_frame": u_hat,
        "jump_windows": jump_windows,
    }


def _extract_stored_nla_specs(ctrl_obj) -> list:
    if not ctrl_obj:
        return []
    raw_json = ctrl_obj.get("cat_nla_sequence_json", "")
    if raw_json:
        try:
            data = json.loads(raw_json)
            if isinstance(data, list) and len(data) > 0:
                return data
        except Exception:
            pass
    return []


def _shortest_angle_lerp(a0: float, a1: float, t: float) -> float:
    diff = (a1 - a0 + math.pi) % (2.0 * math.pi) - math.pi
    return a0 + diff * max(0.0, min(1.0, float(t)))


def attach_cat_to_locomotion_curve(
    context,
    ctrl_obj,
    curve_obj,
    speed_mps=None,
    loop_path: bool = False,
    flip_forward: bool = False,
    start_pct=None,
    _from_nla_rebuild: bool = False,
) -> tuple:
    """
    Attaches `ctrl_obj` (`CTRL_Cat_*`) to `curve_obj` by baking exact 3D
    `location (X, Y, Z)` and level-body `rotation_euler (0, 0, yaw_z)` keyframes onto
    `PathAnim_<ctrl_obj.name>`:
      - `yaw_z` follows the exact curve tangent + per-point `Tilt` (`bp.tilt`),
      - Walking/running NLA strips advance along the curve at exact stride speed (`0.00 mm` foot slip),
      - Stationary NLA strips hold their exact curve position (`0.00 m/s`),
      - Synchronizes ledge elevation climb (`Z_ground -> Z_platform`) with the airborne frames
        of `Cat _Jump  (1_27)`.
    """
    if context is None:
        context = bpy.context
    ctrl_obj = find_cat_controller(ctrl_obj)
    if not ctrl_obj or not curve_obj or curve_obj.type != "CURVE":
        return False, "Select a Black Cat actor (CTRL_Cat) and a 3D Curve."

    if getattr(context, "object", None) and context.object.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass

    tbl = sample_curve_arclength_table_3d(curve_obj)
    arc_len = tbl["total_len"]
    is_cyclic = bool(tbl.get("is_cyclic", False))

    if start_pct is None:
        start_pct = float(ctrl_obj.get("cat_curve_start_pct", 0.0))
    start_pct = float(start_pct) % 100.0
    u0 = start_pct / 100.0

    ctrl_obj["cat_attached_curve"] = curve_obj.name
    ctrl_obj["cat_flip_curve_dir"] = bool(flip_forward)
    ctrl_obj["cat_curve_start_pct"] = round(start_pct, 2)

    nla_specs = _extract_stored_nla_specs(ctrl_obj)
    if nla_specs and not _from_nla_rebuild:
        from .nla_sequencer import rebuild_cat_nla_sequence_from_specs
        rebuild_cat_nla_sequence_from_specs(ctrl_obj, nla_specs, sync_curve=False)
        nla_specs = _extract_stored_nla_specs(ctrl_obj)

    anim_name = resolve_action_name(ctrl_obj.get("cat_anim_name", DEFAULT_WALK_ACTION))
    act = bpy.data.actions.get(anim_name)
    if speed_mps is None:
        speed_mps = get_cat_exact_stride_speed(ctrl_obj, act)
    if speed_mps <= 0.03:
        speed_mps = 0.32
    ctrl_obj["cat_walk_speed"] = float(speed_mps)

    for c in list(ctrl_obj.constraints):
        if c.type == "FOLLOW_PATH":
            ctrl_obj.constraints.remove(c)

    fps = context.scene.render.fps / max(1e-4, context.scene.render.fps_base)
    base_offset = max(0, int(ctrl_obj.get("cat_frame_offset", 0)))
    start_f = 1 + base_offset

    if nla_specs:
        plan = solve_cat_nla_curve_timing_plan(ctrl_obj, nla_specs, curve_obj=curve_obj, fps=fps)
        u_hat = plan["u_hat_per_frame"]
        duration_frames = plan["cycle_frames"]
        jump_windows = plan["jump_windows"]
    else:
        duration_frames = max(12, int(round((arc_len / max(0.05, speed_mps)) * fps)))
        u_hat = [float(tau) / float(duration_frames) for tau in range(duration_frames + 1)]
        jump_windows = []

    if not ctrl_obj.animation_data:
        ctrl_obj.animation_data_create()
    path_act_name = f"PathAnim_{ctrl_obj.name}"
    old_pa = bpy.data.actions.get(path_act_name)
    if old_pa:
        bpy.data.actions.remove(old_pa, do_unlink=True)
    pa = bpy.data.actions.new(name=path_act_name)
    pa.use_fake_user = True
    ctrl_obj.animation_data.action = pa
    bind_action_slot(ctrl_obj.animation_data, pa)

    p_start, _ = query_curve_table_at_u(tbl, 0.0, flip_forward=flip_forward)
    p_end, end_curve_yaw_rad = query_curve_table_at_u(tbl, 1.0, flip_forward=flip_forward)
    z_ground = float(p_start.z)
    z_platform = float(p_end.z)
    has_elevation_jump = (abs(z_platform - z_ground) > 0.12) and (len(jump_windows) > 0)

    use_end_facing = bool(ctrl_obj.get("cat_use_end_facing", False))
    end_facing_rad = math.radians(float(ctrl_obj.get("cat_end_facing_deg", math.degrees(end_curve_yaw_rad))))

    char_scale = max(0.1, float(ctrl_obj.get("cat_char_scale", 1.0)))
    ctrl_obj.rotation_mode = "XYZ"
    ctrl_obj.location = p_start
    ctrl_obj.rotation_euler = (0.0, 0.0, 0.0)
    ctrl_obj.scale = (char_scale, char_scale, char_scale)
    ctrl_obj.keyframe_insert(data_path="location", frame=float(start_f))
    ctrl_obj.keyframe_insert(data_path="rotation_euler", frame=float(start_f))
    bind_action_slot(ctrl_obj.animation_data, pa)

    fcs = get_action_fcurves(pa)
    loc_fcs = [next((fc for fc in fcs if fc.data_path == "location" and fc.array_index == i), None) for i in range(3)]
    rot_z_fc = next((fc for fc in fcs if fc.data_path == "rotation_euler" and fc.array_index == 2), None)

    n_pts = len(u_hat)
    for fc in loc_fcs + [rot_z_fc]:
        if fc and len(fc.keyframe_points) < n_pts:
            fc.keyframe_points.add(n_pts - len(fc.keyframe_points))

    prev_yaw = None
    for tau, uh in enumerate(u_hat):
        frame_val = float(start_f + tau)
        if is_cyclic or (loop_path and u0 > 1e-4):
            u_val = (u0 + uh) % 1.0
        else:
            u_val = min(1.0, max(0.0, u0 + uh))

        pos, yaw_rad = query_curve_table_at_u(tbl, u_val, flip_forward=flip_forward)

        if has_elevation_jump:
            jw = jump_windows[0]
            if tau <= jw["air_start"]:
                pos.z = min(pos.z, z_ground + 0.03)
            elif tau >= jw["air_end"]:
                pos.z = max(pos.z, z_platform - 0.02)
            else:
                u_air = float(tau - jw["air_start"]) / float(max(1, jw["air_end"] - jw["air_start"]))
                u_smooth = u_air * u_air * (3.0 - 2.0 * u_air)
                arc_boost = 0.08 * math.sin(math.pi * u_air)
                pos.z = z_ground + u_smooth * (z_platform - z_ground) + arc_boost

        if use_end_facing and not loop_path and u_val > 0.88:
            t_turn = (u_val - 0.88) / 0.12
            t_turn = t_turn * t_turn * (3.0 - 2.0 * t_turn)
            yaw_rad = _shortest_angle_lerp(yaw_rad, end_facing_rad, t_turn)

        if prev_yaw is not None:
            while yaw_rad - prev_yaw > math.pi:
                yaw_rad -= 2.0 * math.pi
            while yaw_rad - prev_yaw < -math.pi:
                yaw_rad += 2.0 * math.pi
        prev_yaw = yaw_rad

        for axis in range(3):
            if loc_fcs[axis]:
                kp = loc_fcs[axis].keyframe_points[tau]
                kp.co = (frame_val, float(pos[axis]))
                kp.interpolation = "LINEAR"

        if rot_z_fc:
            kp = rot_z_fc.keyframe_points[tau]
            kp.co = (frame_val, float(yaw_rad))
            kp.interpolation = "LINEAR"

    for fc in fcs:
        fc.update()
        for m in list(fc.modifiers):
            fc.modifiers.remove(m)
        if loop_path and fc.data_path != "scale":
            fc.modifiers.new(type="CYCLES")

    # Bake the 4 procedural 'Stray' AAA biomechanical layers using the updated 3D curve & NLA stack
    try:
        from .nla_sequencer import bake_stray_biomechanics_layer as _bake_stray
        _bake_stray(ctrl_obj)
    except Exception as e:
        print(f"[BlackCatStudio] Warning baking Stray biomechanics layer: {e}")

    return (
        True,
        f"'{ctrl_obj.name}' bound to 3D curve '{curve_obj.name}' ({arc_len:.2f} m, {duration_frames}f, zero-slip locked).",
    )


def bake_stray_biomechanics_layer(ctrl_obj) -> dict:
    """Wrapper forwarding to `nla_sequencer.bake_stray_biomechanics_layer(ctrl_obj)`."""
    from .nla_sequencer import bake_stray_biomechanics_layer as _bake_stray
    return _bake_stray(ctrl_obj)


def detach_cat_from_curve(context, ctrl_obj) -> bool:
    ctrl_obj = find_cat_controller(ctrl_obj)
    if not ctrl_obj:
        return False
    if context is None:
        context = bpy.context

    deps = context.evaluated_depsgraph_get()
    mw = ctrl_obj.evaluated_get(deps).matrix_world.copy()

    for c in list(ctrl_obj.constraints):
        if c.type == "FOLLOW_PATH":
            ctrl_obj.constraints.remove(c)

    if ctrl_obj.animation_data:
        ctrl_obj.animation_data_clear()
    pa = bpy.data.actions.get(f"PathAnim_{ctrl_obj.name}")
    if pa:
        try:
            bpy.data.actions.remove(pa, do_unlink=True)
        except Exception:
            pass

    ctrl_obj.matrix_world = mw
    ctrl_obj["cat_attached_curve"] = ""
    return True
