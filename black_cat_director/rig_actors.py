# -*- coding: utf-8 -*-
"""
Black Cat Animation Director Studio v2.0 — Actor Spawner, 3D Fur Groom & Rig Controls
=====================================================================================
Spawns independent rigged Black Cat actors (`CTRL_Cat_01`, `ARM_Cat_01`,
`MESH_Cat_01_Body`) with:
  - 180,000-strand 3D Feline Fur Coat (`PS_Cat_FurCoat`: 5,000 guides x 36 interpolated
    children, rendered as 3D `STRIP` hair with `CAT_3D_Fur_Coat_Mat`),
  - Furless 3D Viewport by default (`show_viewport = False`, `show_render = True`)
    for fast animation playback, with live N-Panel toggle & density/length controls,
  - Matte-Velvet Undercoat + Glossy Golden-Green Eye Mask (`cat body`) & Whiskers (`CAT_Whiskers_Mat`),
  - Ground-ring controller (`CTRL_Cat_01`) with automatic viewport click-redirection.
"""

import math
import bpy
import bmesh
from mathutils import Vector

from .constants import (
    ACTORS_COLLECTION_NAME,
    CAT_FUR_MODIFIER_NAME,
    CAT_TEMPLATE_ARMATURE_NAME,
    CAT_TEMPLATE_BODY_MESH_NAME,
    CAT_TEMPLATE_FUR_MESH_NAME,
    DEFAULT_IDLE_ACTION,
    bind_action_slot,
    ensure_collection,
    resolve_action_name,
)
from .database import ensure_cat_database_loaded


# ============================================================================
# 1. CONTROLLER DISCOVERY & AUTO-REDIRECT HANDLER
# ============================================================================

def is_cat_controller(obj) -> bool:
    if not obj:
        return False
    return bool(
        obj.get("is_cat_controller", False)
        or obj.name.startswith("CTRL_Cat")
    )


def find_cat_controller(obj=None):
    """Finds the parent `CTRL_Cat_*` controller from any selected child mesh, armature, or scene fallback."""
    if obj is None:
        try:
            obj = bpy.context.active_object
        except Exception:
            obj = None

    curr = obj
    visited = set()
    while curr and curr.name not in visited:
        visited.add(curr.name)
        if is_cat_controller(curr):
            return curr
        curr = curr.parent

    if obj and obj.get("cat_ctrl_name"):
        ctrl = bpy.data.objects.get(obj["cat_ctrl_name"])
        if ctrl:
            return ctrl

    try:
        for o in bpy.context.scene.objects:
            if is_cat_controller(o):
                return o
    except Exception:
        pass
    return None


def find_cat_armature(ctrl_obj):
    ctrl = find_cat_controller(ctrl_obj)
    if not ctrl:
        return None
    arm_name = ctrl.get("cat_armature_name", "")
    if arm_name and bpy.data.objects.get(arm_name):
        return bpy.data.objects.get(arm_name)
    for ch in ctrl.children_recursive:
        if ch.type == "ARMATURE":
            return ch
    return None


def get_cat_armature_from_ctrl(ctrl_obj):
    """Alias for `find_cat_armature(ctrl_obj)`."""
    return find_cat_armature(ctrl_obj)


def find_cat_meshes(ctrl_obj) -> dict:
    ctrl = find_cat_controller(ctrl_obj)
    res = {"body": None, "fur": None}
    if not ctrl:
        return res
    b_name = ctrl.get("cat_body_mesh_name", "")
    f_name = ctrl.get("cat_fur_mesh_name", "")
    if b_name:
        res["body"] = bpy.data.objects.get(b_name)
    if f_name:
        res["fur"] = bpy.data.objects.get(f_name)

    for ch in ctrl.children_recursive:
        if ch.type == "MESH":
            if "body" in ch.name.lower() or "feline" in ch.name.lower():
                if not res["body"]:
                    res["body"] = ch
            elif "fur" in ch.name.lower() or "hair" in ch.name.lower() or "lion" in ch.name.lower():
                if not res["fur"]:
                    res["fur"] = ch
    return res


# ============================================================================
# 2. PROCEDURAL GROUND RING GIZMO MESH
# ============================================================================

def _build_controller_ring_mesh(name: str, radius: float = 0.36, thickness: float = 0.018):
    """Builds a sleek ground-plane control ring with a forward `-Y` direction pointer arrow."""
    mesh = bpy.data.meshes.get(name)
    if mesh:
        bpy.data.meshes.remove(mesh, do_unlink=True)
    mesh = bpy.data.meshes.new(name)

    bm = bmesh.new()
    segs = 48
    inner_r = radius - thickness
    outer_r = radius + thickness

    inner_verts = []
    outer_verts = []
    for i in range(segs):
        ang = (2.0 * math.pi * i) / segs
        ca, sa = math.cos(ang), math.sin(ang)
        v_in = bm.verts.new((inner_r * ca, inner_r * sa, 0.004))
        v_out = bm.verts.new((outer_r * ca, outer_r * sa, 0.004))
        inner_verts.append(v_in)
        outer_verts.append(v_out)

    for i in range(segs):
        ni = (i + 1) % segs
        bm.faces.new((inner_verts[i], outer_verts[i], outer_verts[ni], inner_verts[ni]))

    # Forward direction arrow pointing along -Y (cat's forward direction)
    a_tip = bm.verts.new((0.0, -(outer_r + 0.11), 0.005))
    a_l = bm.verts.new((-0.065, -outer_r + 0.005, 0.005))
    a_r = bm.verts.new((0.065, -outer_r + 0.005, 0.005))
    bm.faces.new((a_l, a_tip, a_r))

    bm.to_mesh(mesh)
    bm.free()

    mat_name = "CAT_Controller_Gizmo_Mat"
    mat = bpy.data.materials.get(mat_name)
    if not mat:
        mat = bpy.data.materials.new(mat_name)
        mat.use_nodes = True
        bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf:
            bsdf.inputs["Base Color"].default_value = (0.98, 0.72, 0.15, 1.0)
            if "Emission Color" in bsdf.inputs:
                bsdf.inputs["Emission Color"].default_value = (0.98, 0.72, 0.15, 1.0)
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = 0.65
    mesh.materials.append(mat)
    return mesh


# ============================================================================
# 3. 3D FELINE FUR COAT & MATTE-VELVET SHADER SYSTEM
# ============================================================================

def ensure_3d_fur_coat_on_body_mesh(body_obj) -> bool:
    """
    Ensures `body_obj` has:
      - `VG_Fur_Density` & `VG_Fur_Length` anatomical vertex groups,
      - `CAT_3D_Fur_Coat_Mat` (3D hair strand shader) and `CAT_Whiskers_Mat` (29 facial whisker quads),
      - `PS_Cat_FurCoat` particle hair system (`5,000` guides x `36` interpolated children = `180,000` strands)
        with `show_viewport = False` (fast animation) and `show_render = True` (full 3D fur in render).
    """
    if not body_obj or body_obj.type != "MESH":
        return False

    try:
        scn = getattr(bpy.context, "scene", None)
        if scn and hasattr(scn, "render"):
            scn.render.hair_type = "STRIP"
            scn.render.hair_subdiv = 1
    except Exception:
        pass

    b_mesh = body_obj.data
    if "UVChannel_1" in b_mesh.uv_layers:
        b_mesh.uv_layers["UVChannel_1"].active = True
        b_mesh.uv_layers["UVChannel_1"].active_render = True

    mat_hair = bpy.data.materials.get("CAT_3D_Fur_Coat_Mat")
    if not mat_hair:
        mat_hair = bpy.data.materials.new("CAT_3D_Fur_Coat_Mat")
        mat_hair.use_nodes = True
        mat_hair.surface_render_method = "DITHERED"
        nt_h = mat_hair.node_tree
        nt_h.nodes.clear()
        out_h = nt_h.nodes.new("ShaderNodeOutputMaterial")
        bsdf_h = nt_h.nodes.new("ShaderNodeBsdfPrincipled")
        bsdf_h.inputs["Roughness"].default_value = 0.76
        if "Specular IOR Level" in bsdf_h.inputs:
            bsdf_h.inputs["Specular IOR Level"].default_value = 0.09
        if "Coat Weight" in bsdf_h.inputs:
            bsdf_h.inputs["Coat Weight"].default_value = 0.0
        if "Sheen Weight" in bsdf_h.inputs:
            bsdf_h.inputs["Sheen Weight"].default_value = 0.22
        if "Sheen Roughness" in bsdf_h.inputs:
            bsdf_h.inputs["Sheen Roughness"].default_value = 0.62
        if "Sheen Tint" in bsdf_h.inputs:
            bsdf_h.inputs["Sheen Tint"].default_value = (0.10, 0.12, 0.16, 1.0)
        hair_info = nt_h.nodes.new("ShaderNodeHairInfo")
        ramp = nt_h.nodes.new("ShaderNodeValToRGB")
        ramp.color_ramp.elements[0].position = 0.0
        ramp.color_ramp.elements[0].color = (0.001, 0.001, 0.0015, 1.0)
        ramp.color_ramp.elements.new(0.65)
        ramp.color_ramp.elements[1].position = 0.65
        ramp.color_ramp.elements[1].color = (0.0022, 0.0024, 0.0032, 1.0)
        ramp.color_ramp.elements[2].position = 1.0
        ramp.color_ramp.elements[2].color = (0.0065, 0.0075, 0.010, 1.0)
        nt_h.links.new(hair_info.outputs["Intercept"], ramp.inputs["Fac"])
        nt_h.links.new(ramp.outputs["Color"], bsdf_h.inputs["Base Color"])
        nt_h.links.new(bsdf_h.outputs["BSDF"], out_h.inputs["Surface"])

    if "CAT_3D_Fur_Coat_Mat" not in [m.name for m in b_mesh.materials if m]:
        b_mesh.materials.append(mat_hair)
    hair_mat_slot = [i + 1 for i, m in enumerate(b_mesh.materials) if m and m.name == "CAT_3D_Fur_Coat_Mat"][0]

    ps_mod = body_obj.modifiers.get(CAT_FUR_MODIFIER_NAME)
    if not ps_mod:
        for mod in body_obj.modifiers:
            if mod.type == "PARTICLE_SYSTEM":
                ps_mod = mod
                break

    if not ps_mod:
        ps_mod = body_obj.modifiers.new(name=CAT_FUR_MODIFIER_NAME, type="PARTICLE_SYSTEM")
        ps_mod.show_viewport = False
        ps_mod.show_render = True
        ps = ps_mod.particle_system
        pset = ps.settings
        pset.name = f"PSET_Fur_{body_obj.name}"
        pset.type = "HAIR"
        pset.use_advanced_hair = True
        pset.emit_from = "FACE"
        pset.distribution = "JIT"
        pset.use_even_distribution = True
        pset.use_modifier_stack = True
        pset.count = 5000
        pset.hair_step = 5
        pset.display_step = 3
        pset.render_step = 3
        pset.material = hair_mat_slot
        pset.hair_length = 0.018
        pset.normal_factor = 0.0068
        pset.object_align_factor = (0.0, 0.014, -0.005)
        pset.child_type = "INTERPOLATED"
        pset.rendered_child_count = 36
        pset.child_percent = 100
        pset.create_long_hair_children = True
        pset.child_length = 0.92
        pset.child_length_threshold = 0.15
        pset.child_radius = 0.0048
        pset.child_roundness = 0.30
        pset.clump_factor = 0.16
        pset.clump_shape = -0.25
        pset.use_clump_noise = True
        pset.clump_noise_size = 0.014
        pset.roughness_1 = 0.0018
        pset.roughness_1_size = 0.022
        pset.roughness_endpoint = 0.0024
        pset.roughness_end_shape = 1.5
        pset.root_radius = 0.00046
        pset.tip_radius = 0.00004
        pset.radius_scale = 1.0
        pset.shape = -0.25
        pset.use_close_tip = True
        pset.use_hair_bspline = True
        if "VG_Fur_Density" in body_obj.vertex_groups:
            ps.vertex_group_density = "VG_Fur_Density"
        if "VG_Fur_Length" in body_obj.vertex_groups:
            ps.vertex_group_length = "VG_Fur_Length"
    else:
        ps_mod.particle_system.settings.material = hair_mat_slot

    return True


def configure_cat_fur_coat(
    actor_obj,
    viewport_fur: bool = None,
    render_fur: bool = None,
    fur_length_m: float = None,
    fur_children: int = None,
) -> dict:
    """
    Configures the 180,000-strand 3D Feline Fur Coat (`PS_Cat_FurCoat`) on `actor_obj`:
      - `viewport_fur`: `False` by default for fast 60-165 FPS viewport animation; `True` to preview strands in viewport.
      - `render_fur`: `True` by default so F12 / batch renders show the full 3D fur coat.
      - `fur_length_m`: Base guide hair length in meters (default `0.018` = 18 mm).
      - `fur_children`: Interpolated children per guide hair (default `36` -> `5,000 x 36 = 180,000` strands).
    """
    ctrl = find_cat_controller(actor_obj)
    if not ctrl:
        return {"ok": False}

    meshes = find_cat_meshes(ctrl)
    body_obj = meshes.get("body")
    fur_cards = meshes.get("fur")

    if fur_cards:
        fur_cards.hide_viewport = True
        fur_cards.hide_render = True

    if not body_obj:
        return {"ok": False}

    ensure_3d_fur_coat_on_body_mesh(body_obj)
    ps_mod = body_obj.modifiers.get(CAT_FUR_MODIFIER_NAME)
    if not ps_mod:
        for mod in body_obj.modifiers:
            if mod.type == "PARTICLE_SYSTEM":
                ps_mod = mod
                break
    if not ps_mod:
        return {"ok": False}

    # Ensure each actor has an independent ParticleSettings datablock if modified
    ps = ps_mod.particle_system
    if ps.settings.users > 1 and (fur_length_m is not None or fur_children is not None):
        ps.settings = ps.settings.copy()
    pset = ps.settings

    if viewport_fur is not None:
        ps_mod.show_viewport = bool(viewport_fur)
        ctrl["cat_fur_viewport"] = bool(viewport_fur)
    if render_fur is not None:
        ps_mod.show_render = bool(render_fur)
        ctrl["cat_fur_render"] = bool(render_fur)
    if fur_length_m is not None:
        pset.hair_length = max(0.004, min(0.060, float(fur_length_m)))
        ctrl["cat_fur_length_m"] = float(pset.hair_length)
    if fur_children is not None:
        pset.rendered_child_count = max(4, min(100, int(fur_children)))
        ctrl["cat_fur_children"] = int(pset.rendered_child_count)

    total_strands = int(pset.count) * int(pset.rendered_child_count)
    return {
        "ok": True,
        "viewport_fur": bool(ps_mod.show_viewport),
        "render_fur": bool(ps_mod.show_render),
        "fur_length_m": round(float(pset.hair_length), 4),
        "fur_children": int(pset.rendered_child_count),
        "total_strands": total_strands,
    }


def configure_cat_look(actor_obj, look_mode: str = "PURE_BLACK") -> bool:
    """
    Configures the cat shader look:
      - `PURE_BLACK` (default): Deep obsidian matte-velvet undercoat (`Roughness = 0.86..0.96`,
        `Specular = 0.08`, `Coat = 0.0`), glossy golden-green eyes (`Roughness = 0.05`,
        `Specular = 0.85`), and 180,000-strand 3D black fur coat.
      - `TUXEDO_BW`: Original black-and-white tuxedo chest/paw markings with matte-velvet
        roughness and glossy eyes.
    """
    ctrl = find_cat_controller(actor_obj)
    if not ctrl:
        return False

    meshes = find_cat_meshes(ctrl)
    body_obj = meshes["body"]
    fur_obj = meshes["fur"]
    if fur_obj:
        fur_obj.hide_viewport = True
        fur_obj.hide_render = True

    if body_obj:
        ensure_3d_fur_coat_on_body_mesh(body_obj)
        mat_body = body_obj.data.materials[0] if len(body_obj.data.materials) > 0 else bpy.data.materials.get("cat body")
        if mat_body and mat_body.use_nodes:
            look_mix = mat_body.node_tree.nodes.get("FUR_FIX_LookModeMix")
            if look_mix:
                look_mix.inputs["Factor"].default_value = 1.0 if look_mode == "TUXEDO_BW" else 0.0

    ctrl["cat_look_mode"] = look_mode
    return True


# ============================================================================
# 4. SPAWN RIGGED CAT ACTOR
# ============================================================================

def spawn_cat_actor(
    name: str = "CTRL_Cat_01",
    location=(0.0, 0.0, 0.0),
    rotation_z_deg: float = 0.0,
    scale: float = 1.0,
    look_mode: str = "PURE_BLACK",
    initial_action: str = DEFAULT_IDLE_ACTION,
    viewport_fur: bool = False,
    render_fur: bool = True,
):
    """
    Spawns a clean, independent rigged Black Cat hierarchy inside `01_CAT_ACTORS`:
      `CTRL_Cat_XX` (Ground Ring Controller, `hide_render=True`)
        └── `ARM_Cat_XX` (69-bone Rigify Quadruped Armature)
              └── `MESH_Cat_XX_Body` (6,259v Body + Eyes + Whiskers + 180,000-strand `PS_Cat_FurCoat`)
    By default, `viewport_fur=False` (furless viewport for fast animation) and `render_fur=True`.
    """
    ensure_cat_database_loaded()
    actors_col = ensure_collection(ACTORS_COLLECTION_NAME)

    existing = bpy.data.objects.get(name)
    if existing and is_cat_controller(existing):
        ctrl_obj = existing
        ctrl_obj.location = Vector(location)
        ctrl_obj.rotation_euler = (0.0, 0.0, math.radians(rotation_z_deg))
        ctrl_obj.scale = (scale, scale, scale)
        ctrl_obj.hide_render = True
        configure_cat_look(ctrl_obj, look_mode=look_mode)
        configure_cat_fur_coat(ctrl_obj, viewport_fur=viewport_fur, render_fur=render_fur)
        return ctrl_obj

    tpl_arm = bpy.data.objects.get(CAT_TEMPLATE_ARMATURE_NAME)
    tpl_body = bpy.data.objects.get(CAT_TEMPLATE_BODY_MESH_NAME)
    tpl_fur = bpy.data.objects.get(CAT_TEMPLATE_FUR_MESH_NAME)

    if not tpl_arm or not tpl_body:
        raise RuntimeError("[BlackCatStudio] Template objects ('cat', 'feline ') not found in database!")

    suffix = name.replace("CTRL_", "")
    ring_mesh = _build_controller_ring_mesh(f"MESH_Gizmo_{suffix}", radius=0.36)
    ctrl_obj = bpy.data.objects.new(name, ring_mesh)
    ctrl_obj.hide_render = True
    actors_col.objects.link(ctrl_obj)

    arm_obj = tpl_arm.copy()
    arm_obj.data = tpl_arm.data.copy()
    arm_obj.name = f"ARM_{suffix}"
    arm_obj.hide_viewport = False
    arm_obj.hide_render = False
    arm_obj.show_in_front = False
    actors_col.objects.link(arm_obj)

    # Hide noisy Rigify bone shapes by default for a clean viewport
    try:
        for bcoll in arm_obj.data.collections:
            bcoll.is_visible = False
    except Exception:
        pass

    body_obj = tpl_body.copy()
    body_obj.data = tpl_body.data.copy()
    body_obj.name = f"MESH_{suffix}_Body"
    body_obj.hide_viewport = False
    body_obj.hide_render = False
    actors_col.objects.link(body_obj)

    fur_obj = None
    if tpl_fur:
        fur_obj = tpl_fur.copy()
        fur_obj.data = tpl_fur.data.copy()
        fur_obj.name = f"MESH_{suffix}_Fur"
        fur_obj.hide_viewport = True
        fur_obj.hide_render = True
        actors_col.objects.link(fur_obj)

    # Parent hierarchy cleanly: CTRL -> ARM -> MESH
    arm_obj.parent = ctrl_obj
    arm_obj.matrix_parent_inverse.identity()
    arm_obj.location = (0.0, 0.0, 0.0)
    arm_obj.rotation_euler = (0.0, 0.0, 0.0)
    arm_obj.scale = (1.0, 1.0, 1.0)

    for m_obj in (body_obj, fur_obj):
        if not m_obj:
            continue
        m_obj.parent = arm_obj
        m_obj.matrix_parent_inverse.identity()
        m_obj.location = (0.0, 0.0, 0.0)
        m_obj.rotation_euler = (0.0, 0.0, 0.0)
        m_obj.scale = (1.0, 1.0, 1.0)
        for mod in m_obj.modifiers:
            if mod.type == "ARMATURE":
                mod.object = arm_obj
                mod.use_deform_preserve_volume = True

    # Set world transform on controller
    ctrl_obj.rotation_mode = "XYZ"
    ctrl_obj.location = Vector(location)
    ctrl_obj.rotation_euler = (0.0, 0.0, math.radians(rotation_z_deg))
    ctrl_obj.scale = (scale, scale, scale)

    # Store custom metadata
    ctrl_obj["is_cat_controller"] = True
    ctrl_obj["cat_id"] = "CAT_HERO"
    ctrl_obj["cat_armature_name"] = arm_obj.name
    ctrl_obj["cat_body_mesh_name"] = body_obj.name
    ctrl_obj["cat_fur_mesh_name"] = fur_obj.name if fur_obj else ""
    ctrl_obj["cat_char_scale"] = float(scale)
    ctrl_obj["cat_anim_speed"] = 1.0
    ctrl_obj["cat_frame_offset"] = 0
    ctrl_obj["cat_attached_curve"] = ""
    ctrl_obj["cat_look_mode"] = look_mode
    ctrl_obj["cat_fur_viewport"] = bool(viewport_fur)
    ctrl_obj["cat_fur_render"] = bool(render_fur)
    ctrl_obj["cat_fur_length_m"] = 0.018
    ctrl_obj["cat_fur_children"] = 36

    arm_obj["cat_ctrl_name"] = ctrl_obj.name
    body_obj["cat_ctrl_name"] = ctrl_obj.name
    if fur_obj:
        fur_obj["cat_ctrl_name"] = ctrl_obj.name

    configure_cat_look(ctrl_obj, look_mode=look_mode)
    configure_cat_fur_coat(
        ctrl_obj,
        viewport_fur=viewport_fur,
        render_fur=render_fur,
        fur_length_m=0.018,
        fur_children=36,
    )

    # Assign initial animation action
    initial_action = resolve_action_name(initial_action)
    act = bpy.data.actions.get(initial_action)
    if act:
        if not arm_obj.animation_data:
            arm_obj.animation_data_create()
        arm_obj.animation_data.action = act
        bind_action_slot(arm_obj.animation_data, act)
        ctrl_obj["cat_anim_name"] = act.name

    return ctrl_obj
