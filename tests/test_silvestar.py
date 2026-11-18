# -*- coding: utf-8 -*-
"""
Provjera Silvestra u praznom Blenderu:
  Blender -b --factory-startup -P tests/test_silvestar.py
"""
import os
import sys
import bpy

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
import black_cat_director as cd


def tip_positions(arm, frames):
    out = []
    for f in frames:
        bpy.context.scene.frame_set(f)
        ae = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
        out.append({n: ae.pose.bones[n].matrix.translation.copy() for n in ("DEF-spine.006", "DEF-tail.006", "DEF-hand.L", "DEF-foot.R", "DEF-jaw")if n in ae.pose.bones})
    return out


def run():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    cd.register()

    print("=== [1] append_silvestar: kolekcija SILVESTAR i sve akcije ===")
    ctrl = cd.append_silvestar()
    assert ctrl is not None and ctrl.name == "CTRL_Silvestar"
    col = bpy.data.collections.get("SILVESTAR")
    assert col and {o.name for o in col.objects} >= {"CTRL_Silvestar", "ARM_Silvestar", "MESH_Silvestar_Body"}
    for name in cd.SILVESTAR_CATALOG:
        assert name in bpy.data.actions, f"nema akcije {name}"
    arm = bpy.data.objects["ARM_Silvestar"]
    body = bpy.data.objects["MESH_Silvestar_Body"]
    assert any(m.type == "PARTICLE_SYSTEM" and m.show_render and not m.show_viewport for m in body.modifiers), "krzno: render da, viewport ne"

    print("=== [2] sve kombinacije se slažu u NLA ===")
    for pid, label in cd.list_silvestar_presets():
        ok, msg = cd.apply_silvestar_preset(ctrl, pid)
        assert ok, msg
        strips = [s for t in arm.animation_data.nla_tracks for s in t.strips]
        assert strips, pid
        assert not any(t.name.startswith("CAT_Stray") for t in arm.animation_data.nla_tracks)
        print(f"  {pid:20s} {len(strips)} isječaka, kraj f{bpy.context.scene.frame_end}  ({label})")

    print("=== [3] petlje se zatvaraju bez skoka (zadnji kadar = prvi) ===")
    for name in (cd.silvestar.A_IDLE, cd.silvestar.A_TALK, cd.silvestar.A_LICK):
        act = bpy.data.actions[name]
        arm.animation_data_clear()
        ad = arm.animation_data_create()
        ad.action = act
        ad.action_slot = act.slots[0]
        n = int(act.frame_end)
        a, b, c = tip_positions(arm, [1, n, n - 1])
        seam = max((a[k] - b[k]).length for k in a)
        step = max((c[k] - b[k]).length for k in a)
        print(f"  {name}: {n - 1} kadrova, šav {seam * 1000:.3f} mm, zadnji korak {step * 1000:.2f} mm")
        assert seam < 0.0005, f"{name}: šav {seam * 1000:.2f} mm"
        assert step < 0.02
        # mačak se stvarno miče (disanje, rep)
        pts = tip_positions(arm, range(1, n, 6))
        rng = max((p["DEF-tail.006"] - pts[0]["DEF-tail.006"]).length for p in pts)
        assert rng > 0.01, f"{name}: rep se ne miče"

    print("=== [4] skok: počinje na podu 1,34 m ispod podesta, završava na mjestu sjedenja ===")
    act = bpy.data.actions[cd.silvestar.A_JUMP]
    arm.animation_data_clear()
    ad = arm.animation_data_create()
    ad.action = act
    ad.action_slot = act.slots[0]
    p0, p1 = tip_positions(arm, [1, int(act.frame_end)])
    dz = p1["DEF-foot.R"].z - p0["DEF-foot.R"].z
    print(f"  stražnja šapa se digne {dz:.3f} m")
    assert 1.2 < dz < 1.5

    print("=== [5] klipovi rade i na Black Cat mačku iz knjižnice plugina ===")
    cd.integrate_cat_studio(spawn_demo=False)
    cat = cd.spawn_cat("CTRL_Cat_01", location=(2.0, 0.0, 0.0))
    ok, msg = cd.apply_silvestar_preset(cat, "PREDSTAVA")
    assert ok, msg
    arm2 = bpy.data.objects[cat["cat_armature_name"]]
    miss = set()
    for name in cd.SILVESTAR_CATALOG:
        act = bpy.data.actions[name]
        for fc in act.layers[0].strips[0].channelbags[0].fcurves:
            if fc.data_path.startswith('pose.bones["'):
                bn = fc.data_path.split('"')[1]
                if bn not in arm2.pose.bones:
                    miss.add(bn)
    assert not miss, f"kosti kojih nema u rigu knjižnice: {sorted(miss)}"
    ok, msg = cd.apply_silvestar_preset(ctrl, "IDLE")
    cd.apply_silvestar_preset(cat, "IDLE")
    a = tip_positions(arm, [1, 60, 140])
    b = tip_positions(arm2, [1, 60, 140])
    d = max((a[i][k] - b[i][k]).length for i in range(3) for k in a[i])
    print(f"  ista poza na oba riga, najveća razlika {d * 1000:.2f} mm")
    assert d < 0.005
    print("SVI TESTOVI SILVESTRA PROŠLI")


if __name__ == "__main__":
    run()
