# -*- coding: utf-8 -*-
"""
Slaže `silvestar_studio.blend`: kolekcija SILVESTAR (kontroler, rig, tijelo, krzno) + sve
finalne animacije kao obične akcije + studijska scena + ugrađen bootstrap plugina.

Ulaz su uzorci animacija (`smp_<ključ>.npz`) koje iz produkcijskih S1 datoteka vadi
`tools/extract_silvestar_samples.py` (NLA slojevi spojeni u vrijednosti kontrola po kadru).

  Blender -b --factory-startup --python tools/build_silvestar_studio.py -- <mapa_uzoraka> <izvorni_S1.blend> [izlaz.blend]
"""
import bpy, sys, os, json, math
import numpy as np
from mathutils import Matrix, Quaternion, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
SMP, SRC = argv[0], argv[1]
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = argv[2] if len(argv) > 2 else os.path.join(REPO, "silvestar_studio.blend")
sys.path.insert(0, REPO)
import black_cat_director as cd
from black_cat_director import silvestar as sil

scn = bpy.context.scene
scn.render.fps = 24
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o, do_unlink=True)

# ---------------------------------------------------------------- 1. Silvestar iz produkcijske scene
SRC_NAMES = ["CTRL_Silvestar_01", "ARM_Silvestar_01", "MESH_Silvestar_01_Body", "MESH_Silvestar_01_Fur"]
with bpy.data.libraries.load(SRC, link=False) as (df, dt):
    dt.objects = [n for n in SRC_NAMES if n in df.objects]
ctrl, arm, body, fur = [bpy.data.objects[n] for n in SRC_NAMES]
col = bpy.data.collections.new(sil.SILVESTAR_COLLECTION)
scn.collection.children.link(col)
for o in (ctrl, arm, body, fur):
    col.objects.link(o)
for o in (ctrl, arm):
    if o.animation_data:
        o.animation_data_clear()
for pb in arm.pose.bones:
    for k in list(pb.constraints):
        t = getattr(k, "target", None)
        if t is not None and t != arm:
            print("uklonjen vanjski constraint", pb.name, k.name)
            pb.constraints.remove(k)
    pb.matrix_basis = Matrix.Identity(4)
keep = {ctrl, arm, body, fur}
for o in list(bpy.data.objects):
    if o not in keep:
        bpy.data.objects.remove(o, do_unlink=True)
for a in list(bpy.data.actions):
    # mačje akcije iz produkcijske scene ostaju (npr. Cat_Seated_Watch_Lift), slojevi vožnje ne
    a.use_fake_user = a.name.startswith(("Cat", "cat", "FP ", "P cat"))
for t in list(bpy.data.texts):
    if arm.get("rig_ui") != t:
        bpy.data.texts.remove(t)
bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

ctrl.name, arm.name, body.name, fur.name = sil.SILVESTAR_CTRL, "ARM_Silvestar", "MESH_Silvestar_Body", "MESH_Silvestar_Fur"
ctrl.parent = None
for k in list(ctrl.keys()):
    if k.startswith(("cat_", "silvestar", "is_cat")):
        del ctrl[k]
for k in list(arm.keys()):
    if k.startswith(("cat_", "silvestar")):
        del arm[k]
ctrl["cat_is_controller"] = True
ctrl["is_cat_controller"] = True
ctrl["silvestar_actor"] = True
ctrl["cat_armature_name"] = arm.name
ctrl["cat_body_name"] = body.name
ctrl["cat_body_mesh_name"] = body.name
ctrl["cat_fur_name"] = fur.name
ctrl["cat_anim_speed"] = 1.0
ctrl["cat_frame_offset"] = 0
ctrl["cat_loop_anim"] = False
ctrl["cat_char_scale"] = 1.0
ctrl["cat_attached_curve"] = ""
ctrl["cat_look_mode"] = "ORIGINAL"
arm["cat_is_template"] = False
arm["cat_controller_name"] = ctrl.name
arm["cat_ctrl_name"] = ctrl.name
ctrl.hide_render = True
ctrl.location = (0, 0, 0)
ctrl.rotation_euler = (0, 0, 0)
ctrl.scale = (1, 1, 1)
print("ARM lokalno", [round(x, 5) for x in arm.location], [round(x, 5) for x in arm.rotation_euler])
bpy.context.view_layer.update()

# ---------------------------------------------------------------- 2. pomoćne funkcije
I16 = np.eye(4, dtype=np.float64).ravel()
PROP_KEYS = ("IK_FK", "IK_Stretch", "IK_parent", "pole_vector", "pole_parent", "FK_limb_follow",
             "neck_follow", "head_follow", "tail_follow", "torso_parent", "eyes_follow", "mouth_lock")
ROOT_REST = arm.data.bones["root"].matrix_local.copy()


def load(key):
    d = np.load(os.path.join(SMP, "smp_%s.npz" % key))
    return dict(basis=d["basis"].astype(np.float64), props=d["props"], armw=d["armw"].reshape(-1, 4, 4),
                defm=d["defm"].astype(np.float64), names=[str(n) for n in d["names"]],
                propnames=[str(n) for n in d["propnames"]], defnames=[str(n) for n in d["defnames"]], f0=int(d["f0"]))


def smoothstep(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3 - 2 * x)


def make_clip(smp, fa, fb, anchor="start", loop=False, seam=20, breath=0.0, prop_override=None, tail_unchain=False):
    """Vraća kanale {(kost, 'loc'|'quat'|'scl'): [F, n]} za kadrove fa..fb (uključivo)."""
    i0, i1 = fa - smp["f0"], fb - smp["f0"]
    B = smp["basis"][i0:i1 + 1]
    F = len(B)
    names = smp["names"]
    armw = smp["armw"][i0:i1 + 1]
    A = {"start": armw[0], "end": armw[-1]}[anchor]
    Ainv = np.linalg.inv(A)
    D = np.einsum("ij,fjk->fik", Ainv, armw)
    root_moves = np.abs(D - np.eye(4)).max() > 1e-6
    ch = {}
    for bi, n in enumerate(names):
        M = B[:, bi, :]
        is_root = (n == "root")
        if not is_root and np.abs(M - I16).max() < 1e-6:
            continue
        if n not in arm.pose.bones:
            continue
        loc = np.zeros((F, 3)); quat = np.zeros((F, 4)); scl = np.ones((F, 3))
        prev = None
        for f in range(F):
            m = Matrix(M[f].reshape(4, 4).tolist())
            if is_root:
                if not root_moves and np.abs(M[f] - I16).max() < 1e-6:
                    quat[f] = (1, 0, 0, 0); continue
                m = ROOT_REST.inverted() @ Matrix(D[f].tolist()) @ ROOT_REST @ m
            l, q, s = m.decompose()
            if prev is not None and q.dot(prev) < 0:
                q.negate()
            prev = q.copy()
            loc[f] = l; quat[f] = q; scl[f] = s
        if is_root and not root_moves and np.abs(M - I16).max() < 1e-6:
            continue
        ch[(n, "loc")] = loc; ch[(n, "quat")] = quat; ch[(n, "scl")] = scl
    if tail_unchain:
        # Rig prednjeg mačka nema lanac Copy Rotation na repu (tail.003-006). Standardni rig ga ima,
        # pa se rotacija svakog članka preračuna tako da nakon lanca da isti konačni kut.
        TAIL = ("tail.001", "tail.002", "tail.003", "tail.004", "tail.005", "tail.006")
        ident = np.tile(np.array([1.0, 0, 0, 0]), (F, 1))
        fin = {n: (ch[(n, "quat")].copy() if (n, "quat") in ch else ident.copy()) for n in TAIL + ("tail_master.001",)}
        for n in TAIL:
            if (n, "quat") not in ch:
                ch[(n, "loc")] = np.zeros((F, 3)); ch[(n, "scl")] = np.ones((F, 3)); ch[(n, "quat")] = ident.copy()
        for n in TAIL:
            pb = arm.pose.bones.get(n)
            con = next((k for k in pb.constraints if k.type == "COPY_ROTATION"), None) if pb else None
            if con is None or n not in fin or con.subtarget not in fin:
                continue
            prev = fin[con.subtarget]
            q = ch[(n, "quat")]
            last = None
            for f in range(F):
                pq, cq = Quaternion(prev[f]), Quaternion(fin[n][f])
                r = (pq.inverted() @ cq) if con.mix_mode == "BEFORE" else (cq @ pq.inverted())
                if last is not None and r.dot(last) < 0:
                    r.negate()
                last = r.copy(); q[f] = r
            print("rep", n, con.mix_mode, con.owner_space, con.target_space)
    if loop:
        # zadnji kadar mora biti jednak prvom: razlika se skida glatko kroz zadnjih `seam` kadrova
        w = smoothstep((np.arange(F) - (F - 1 - seam)) / float(seam))[:, None]
        for k, v in ch.items():
            v -= w * (v[-1] - v[0])
            if k[1] == "quat":
                v /= np.linalg.norm(v, axis=1)[:, None]
    if breath > 0.0:
        # disanje: prsa, vrat i zdjelica oko lokalne osi X (isto kao sloj disanja u vožnji), cijeli broj udaha u petlji
        L = F - 1
        n_b = max(1, int(round(L / 82.0)))
        ph = 2 * math.pi * n_b * np.arange(F) / float(L)
        s1 = np.sin(ph)
        for bone, deg in (("chest", 1.0 * breath), ("neck", 0.5 * breath), ("hips", -0.4 * breath)):
            if (bone, "quat") not in ch:
                ch[(bone, "loc")] = np.zeros((F, 3)); ch[(bone, "scl")] = np.ones((F, 3))
                ch[(bone, "quat")] = np.tile(np.array([1.0, 0, 0, 0]), (F, 1))
            q = ch[(bone, "quat")]
            for f in range(F):
                r = Quaternion(q[f]) @ Quaternion((1, 0, 0), math.radians(deg * s1[f]))
                q[f] = r
    props = {}
    for j, pn in enumerate(smp["propnames"]):
        bn, k = pn.split("|")
        if k in PROP_KEYS and bn in arm.pose.bones and k in arm.pose.bones[bn].keys():
            props[(bn, k)] = float(smp["props"][i0, j])
            if prop_override and k in prop_override:
                props[(bn, k)] = prop_override[k]
    # provjera: DEF kosti u prostoru armature, relativno prema sidru
    check = None
    if not loop and breath == 0.0:
        allm = np.einsum("fij,fbjk->fbik", D, smp["defm"][i0:i1 + 1].reshape(F, -1, 4, 4))
        check = dict(frames=list(range(0, F, max(1, F // 12))), names=smp["defnames"], mats=allm)
    return dict(ch=ch, F=F, props=props, check=check, D=D, def_all=(check["mats"] if check else None))


def rdp(t, v, tol):
    keep = np.zeros(len(t), bool); keep[0] = keep[-1] = True
    stack = [(0, len(t) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = v[a] + (v[b] - v[a]) * (t[a + 1:b] - t[a]) / (t[b] - t[a])
        err = np.abs(v[a + 1:b] - seg)
        i = int(err.argmax())
        if err[i] > tol:
            m = a + 1 + i
            keep[m] = True
            stack.append((a, m)); stack.append((m, b))
    return keep


def write_action(name, clip, loop=False):
    old = bpy.data.actions.get(name)
    if old:
        bpy.data.actions.remove(old)
    act = bpy.data.actions.new(name)
    act.use_fake_user = True
    slot = act.slots.new(id_type="OBJECT", name="Silvestar")
    layer = act.layers.new("Layer")
    strip = layer.strips.new(type="KEYFRAME")
    bag = strip.channelbag(slot, ensure=True)
    F = clip["F"]
    t = np.arange(1, F + 1, dtype=np.float64)
    nk = 0

    def put(dp, idx, vals, tol, grp):
        nonlocal nk
        if np.ptp(vals) < 1e-7:
            tt, vv = t[:1], vals[:1]
        else:
            k = rdp(t, vals, tol)
            tt, vv = t[k], vals[k]
        fc = bag.fcurves.new(dp, index=idx, group_name=grp)
        fc.keyframe_points.add(len(tt))
        co = np.empty(len(tt) * 2); co[0::2] = tt; co[1::2] = vv
        fc.keyframe_points.foreach_set("co", co)
        for kp in fc.keyframe_points:
            kp.interpolation = "LINEAR"
        fc.update()
        nk += len(tt)

    for (bn, kind), v in clip["ch"].items():
        pb = arm.pose.bones[bn]
        base = 'pose.bones["%s"].' % bn
        if kind == "loc":
            if np.abs(v).max() > 1e-6:
                for i in range(3):
                    put(base + "location", i, v[:, i], 2e-5, bn)
        elif kind == "scl":
            if np.abs(v - 1).max() > 1e-5:
                for i in range(3):
                    put(base + "scale", i, v[:, i], 1e-4, bn)
        else:
            if np.abs(v - np.array([1, 0, 0, 0])).max() < 1e-6:
                continue
            if pb.rotation_mode == "QUATERNION":
                for i in range(4):
                    put(base + "rotation_quaternion", i, v[:, i], 1e-4, bn)
            else:
                e = np.zeros((F, 3)); prev = None
                for f in range(F):
                    q = Quaternion(v[f])
                    ee = q.to_euler(pb.rotation_mode, prev) if prev is not None else q.to_euler(pb.rotation_mode)
                    prev = ee; e[f] = ee
                for i in range(3):
                    put(base + "rotation_euler", i, e[:, i], 2e-4, bn)
    for (bn, k), val in clip["props"].items():
        put('pose.bones["%s"]["%s"]' % (bn, k), 0, np.array([val]), 0, bn)
    act.use_frame_range = True
    act.frame_start = 1
    act.frame_end = F
    act.use_cyclic = bool(loop)
    meta = sil.SILVESTAR_CATALOG[name]
    act["cat_category"] = meta["category"]; act["cat_label"] = meta["label"]
    act["cat_is_locomotion"] = False; act["cat_speed_mps"] = 0.0; act["cat_role"] = "FIXED"
    act["silvestar_loop"] = bool(loop)
    return act, nk


def verify(act, clip):
    if not clip["check"]:
        return None
    ad = arm.animation_data or arm.animation_data_create()
    for tr in list(ad.nla_tracks):
        ad.nla_tracks.remove(tr)
    ad.action = act
    ad.action_slot = act.slots[0]
    worst = 0.0; wname = ""; clip["paw_mm"] = 0.0
    for f in clip["check"]["frames"]:
        scn.frame_set(f + 1)
        dg = bpy.context.evaluated_depsgraph_get()
        ae = arm.evaluated_get(dg)
        for j, n in enumerate(clip["check"]["names"]):
            pb = ae.pose.bones.get(n)
            if pb is None:
                continue
            e = (pb.matrix.translation - Vector(clip["check"]["mats"][f, j][:3, 3])).length
            if e > worst:
                worst, wname = e, n
            if n in ("DEF-foot.L", "DEF-foot.R", "DEF-hand.L", "DEF-hand.R", "DEF-tail.006", "DEF-spine.006"):
                clip["paw_mm"] = max(clip["paw_mm"], e * 1000)
    ad.action = None
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
        for k in pb.keys():
            pass
    return worst, wname

def refine_limbs(act, clip, pairs, iters=3):
    """
    Šape na isto mjesto kao u izvornoj sceni: IK kontrola se po kadru pomakne za razliku
    između očekivanog i stvarnog položaja DEF kosti šape (rig prednjeg mačka ima isključeno
    rastezanje nogu i šape drži na svjetskim metama, standardni rig ne).
    """
    smp_def = clip["def_all"]; dn = clip["check"]["names"]
    ad = arm.animation_data or arm.animation_data_create()
    for tr in list(ad.nla_tracks):
        ad.nla_tracks.remove(tr)
    ad.action = act; ad.action_slot = act.slots[0]
    worst = 0.0
    for f in range(clip["F"]):
        scn.frame_set(f + 1)
        for it in range(iters):
            bpy.context.view_layer.update()
            for cb, db in pairs:
                pb = arm.pose.bones[cb]
                exp = Vector(smp_def[f, dn.index(db)][:3, 3])
                e = exp - arm.pose.bones[db].matrix.translation
                if it == 0:
                    worst = max(worst, e.length)
                if e.length < 2e-5:
                    continue
                m = pb.matrix.copy(); m.translation = m.translation + e
                pb.matrix_basis = arm.convert_space(pose_bone=pb, matrix=m, from_space="POSE", to_space="LOCAL")
        for cb, db in pairs:
            clip["ch"][(cb, "loc")][f] = arm.pose.bones[cb].location
    ad.action = None
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    print("refine_limbs: najveći ispravak %.1f mm" % (worst * 1000))


# ---------------------------------------------------------------- 3. klipovi
v16, idle, jump, cat02 = load("v16"), load("idle"), load("jump"), load("cat02")
CLIPS = [
    (sil.A_IDLE,   make_clip(idle, 340, 625, loop=True, seam=24, breath=2.0), True,  "S1 f340-625 (sjedeći idle + rep), dodano disanje"),
    (sil.A_TALK,   make_clip(v16, 352, 639, loop=True, seam=20, breath=2.0), True,  "S1 f352-639 (govor u kameru + rep), dodano disanje"),
    (sil.A_LICK,   make_clip(v16, 51, 141, loop=True, seam=16), True,                "S1 f51-141 (v16 lizanje na boku)"),
    (sil.A_SHOCK,  make_clip(v16, 141, 304), False,                                   "S1 f141-304 (lizanje, kabina tresne f176, šok, sjedne)"),
    (sil.A_JUMP,   make_clip(jump, 484, 580, anchor="end"), False,                   "v06 f484-580 (čučanj, skok 1,34 m, sjedanje); sidro je mjesto sjedenja"),
    (sil.A_LEVER,  make_clip(v16, 640, 736), False,                                   "S1 f640-736 (šapa gurne polugu)"),
    (sil.A_MASTER, make_clip(v16, 1, 760), False,                                     "S1 f1-760 (cijela izvedba v16)"),
    (sil.A_S02,    make_clip(cat02, 1, 476, prop_override={"IK_Stretch": 1.0}, tail_unchain=True), False,                                   "S1 prednji mačak f1-476 (v14), sidro je početak"),
]
report = {"clips": []}
LIMBS = [("foot_ik.L", "DEF-foot.L"), ("foot_ik.R", "DEF-foot.R"), ("hand_ik.L", "DEF-hand.L"), ("hand_ik.R", "DEF-hand.R")]
for name, clip, loop, src in CLIPS:
    act, nk = write_action(name, clip, loop)
    if name == sil.A_S02:
        refine_limbs(act, clip, LIMBS)
        act, nk = write_action(name, clip, loop)
    v = verify(act, clip)
    D = clip["D"]
    rec = dict(name=name, label=sil.SILVESTAR_CATALOG[name]["label"], frames=clip["F"], seconds=round(clip["F"] / 24.0, 2), loop=loop,
               keys=nk, channels=len(act.layers[0].strips[0].channelbags[0].fcurves), source=src,
               root_start=[round(float(x), 4) for x in D[0][:3, 3]], root_end=[round(float(x), 4) for x in D[-1][:3, 3]],
               verify_mm=None if v is None else round(v[0] * 1000, 3), verify_bone=None if v is None else v[1],
               verify_paws_tail_head_mm=None if v is None else round(clip["paw_mm"], 3))
    report["clips"].append(rec)
    print("CLIP", json.dumps(rec, ensure_ascii=False))

# Svaki klip mora imati ključ na svakom kanalu koji koristi bilo koji Silvestrov klip. Bez toga kanal
# koji u klipu miruje (npr. kapci u priči) "procuri" iz donjeg NLA isječka koji drži zadnju pozu (lizanje žmiri).
union = {}
for name in sil.SILVESTAR_CATALOG:
    for fc in bpy.data.actions[name].layers[0].strips[0].channelbags[0].fcurves:
        if '"]["' in fc.data_path:
            continue
        union[(fc.data_path, fc.array_index)] = fc.group.name if fc.group else ""
filled = 0
for name in sil.SILVESTAR_CATALOG:
    bag = bpy.data.actions[name].layers[0].strips[0].channelbags[0]
    have = {(fc.data_path, fc.array_index) for fc in bag.fcurves}
    for (dp, idx), grp in union.items():
        if (dp, idx) in have:
            continue
        val = 1.0 if (dp.endswith("scale") or (dp.endswith("rotation_quaternion") and idx == 0)) else 0.0
        fc = bag.fcurves.new(dp, index=idx, group_name=grp)
        fc.keyframe_points.add(1)
        fc.keyframe_points[0].co = (1.0, val)
        fc.keyframe_points[0].interpolation = "LINEAR"
        fc.update(); filled += 1
print("UNION kanala", len(union), "dopunjeno", filled)
report["channels_per_clip"] = len(union)

# ---------------------------------------------------------------- 4. ostale mačje akcije iz knjižnice plugina
lib = cd.constants.get_library_blend_path()
if os.path.isfile(lib):
    with bpy.data.libraries.load(lib, link=False) as (df, dt):
        dt.actions = [n for n in df.actions if n not in bpy.data.actions and not n.startswith(("PathAnim_", "CAT_"))]
    for a in dt.actions:
        if a:
            a.use_fake_user = True
    cd.database._restore_action_metadata()
report["stock_actions"] = sorted(a.name for a in bpy.data.actions if a.name not in sil.SILVESTAR_CATALOG)

# ---------------------------------------------------------------- 5. studijska scena: podest, pod, svjetla, kamera
H = 1.3446   # visina skoka (S1: pod stanice -> kameni podest)
stage = bpy.data.collections.new("SILVESTAR_Scena")
scn.collection.children.link(stage)

def mat(name, rgb, rough):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    return m

def box(name, x0, x1, y0, y1, z0, z1, m):
    me = bpy.data.meshes.new(name)
    v = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
    f = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    me.from_pydata(v, [], f); me.materials.append(m)
    o = bpy.data.objects.new(name, me); stage.objects.link(o); return o

# podest pokriva tragove šapa nakon doskoka (iz DEF kostiju skoka), s rubom od 12 cm
jc = CLIPS[4][1]["check"]
pts = []
for fi in range(len(jc["mats"])):
    if fi < 40:
        continue
    for j, n in enumerate(jc["names"]):
        p = jc["mats"][fi, j][:3, 3]
        if p[2] < 0.12:
            pts.append(p)
pts = np.array(pts) if pts else np.array([[-.4, -.4, 0], [.4, .4, 0]])
x0, y0 = pts[:, 0].min() - 0.12, pts[:, 1].min() - 0.12
x1, y1 = pts[:, 0].max() + 0.12, pts[:, 1].max() + 0.12
report["podest"] = dict(x=[round(float(x0), 3), round(float(x1), 3)], y=[round(float(y0), 3), round(float(y1), 3)], h=H)
m_st = mat("MAT_Silvestar_Podest", (0.23, 0.22, 0.21), 0.85)
m_fl = mat("MAT_Silvestar_Pod", (0.12, 0.125, 0.14), 0.8)
box("SILVESTAR_Podest", x0, x1, y0, y1, 0.0, H, m_st)
box("SILVESTAR_Pod", -6, 6, -6, 6, -0.05, 0.0, m_fl)
ctrl.location = (0, 0, H)

def light(name, loc, rot, energy, size, color):
    d = bpy.data.lights.new(name, "AREA"); d.energy = energy; d.size = size; d.color = color
    o = bpy.data.objects.new(name, d); o.location = loc; o.rotation_euler = rot; stage.objects.link(o)
light("LGT_Silvestar_Key", (1.9, -2.3, H + 2.0), (0.80, 0, 0.62), 160, 1.8, (1.0, 0.95, 0.88))
light("LGT_Silvestar_Rim", (-1.7, 2.0, H + 1.6), (-0.85, 0, -0.68), 130, 1.5, (0.80, 0.90, 1.0))
light("LGT_Silvestar_Fill", (-2.2, -1.6, H + 0.9), (1.25, 0, -0.95), 35, 2.5, (0.85, 0.9, 1.0))
cam = bpy.data.objects.new("CAM_Silvestar", bpy.data.cameras.new("CAM_Silvestar"))
cam.data.lens = 50
stage.objects.link(cam)
scn.camera = cam
tgt = Vector((0, 0, H + 0.24))
cam.location = (1.75, -2.25, H + 0.55)
cam.rotation_euler = (tgt - cam.location).to_track_quat("-Z", "Y").to_euler()
w = bpy.data.worlds.new("World_Silvestar"); w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.022, 0.028, 1)
scn.world = w
scn.render.engine = "BLENDER_EEVEE"
scn.render.resolution_x, scn.render.resolution_y = 1920, 1080
try:
    scn.render.hair_type = "STRIP"
except Exception:
    pass

# ---------------------------------------------------------------- 6. zadana animacija, bootstrap, spremanje
ok, msg = sil.apply_silvestar_preset(ctrl, "IDLE")
print("PRESET", ok, msg)
boot = os.path.join(REPO, "bootstrap_cat_studio.py")
txt = bpy.data.texts.new("bootstrap_cat_studio.py")
txt.from_string(open(boot, encoding="utf-8").read())
txt.use_module = True
info = bpy.data.texts.new("SILVESTAR_PROCITAJ_ME.txt")
info.from_string("Silvestar Studio — https://github.com/timon2200/black-cat-studio\n\n"
                 "Kolekcija SILVESTAR: CTRL_Silvestar (kontroler), ARM_Silvestar (rig), MESH_Silvestar_Body (tijelo + krzno u renderu).\n"
                 "N-panel > Black Cat Studio > 'Silvestar: gotove animacije' slaže animacije jednim klikom.\n"
                 "Akcije: " + ", ".join(sil.SILVESTAR_CATALOG) + "\n")
for o in bpy.context.view_layer.objects:
    o.select_set(False)
ctrl.select_set(True)
bpy.context.view_layer.objects.active = ctrl
scn.frame_set(1)
try:
    bpy.ops.file.pack_all()
except Exception as e:
    print("pack", e)
imgs = sorted(((i.name, i.size[0], i.size[1], (i.packed_file.size if i.packed_file else 0)) for i in bpy.data.images), key=lambda x: -x[3])
report["images"] = imgs[:20]
report["bones"] = len(arm.pose.bones)
bpy.context.preferences.filepaths.save_version = 0
bpy.ops.wm.save_as_mainfile(filepath=OUT, compress=True)
report["size_mb"] = round(os.path.getsize(OUT) / 1e6, 1)
json.dump(report, open(os.path.join(REPO, "database", "silvestar_clips.json"), "w"), indent=1, ensure_ascii=False)
print("SAVED", OUT, report["size_mb"], "MB")
print("IMAGES", imgs[:12])
