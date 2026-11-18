# -*- coding: utf-8 -*-
"""
Silvestar — gotove animacije crnog mačka iz vožnje „Čarobni lift” (Advent u Varaždinu 2026.)
===========================================================================================
Silvestar je isti rig kao Black Cat (Rigify, 782 kosti), s produkcijskim krznom i
finalnim animacijama složenima za vožnju. Sve animacije su obične Blender akcije
(jedan sloj, ključevi na kontrolama riga), pa rade u NLA sekvenceru ovog plugina
i na svakom mačku stvorenom gumbom „Spawn Black Cat”.

Datoteka `silvestar_studio.blend` (u korijenu repozitorija) sadrži kolekciju
`SILVESTAR` (kontroler, rig, tijelo, krzno) i sve akcije. Ovaj modul:
  - popisuje klipove (`SILVESTAR_CATALOG`) i gotove kombinacije (`SILVESTAR_PRESETS`),
  - učitava Silvestra ili samo njegove akcije u bilo koju scenu,
  - slaže kombinaciju u NLA jednim pozivom (`apply_silvestar_preset`).
"""

import glob
import os
import shutil

import bpy

SILVESTAR_BLEND_NAME = "silvestar_studio.blend"
SILVESTAR_COLLECTION = "SILVESTAR"
SILVESTAR_CTRL = "CTRL_Silvestar"

# Nazivi akcija počinju s "Cat" jer plugin po tom prefiksu prepoznaje mačje akcije.
A_IDLE = "Cat_Silvestar_Sjedi_Idle_Loop"
A_TALK = "Cat_Silvestar_Sjedi_Prica_Loop"
A_LICK = "Cat_Silvestar_Lizanje_Loop"
A_SHOCK = "Cat_Silvestar_Lizanje_Sok_Sjedanje"
A_JUMP = "Cat_Silvestar_Skok_Na_Podest"
A_LEVER = "Cat_Silvestar_Poluga"
A_MASTER = "Cat_Silvestar_Master_Izvedba"
A_S02 = "Cat_Silvestar02_Obilazak_Kabine"


def _meta(label, loop=False, category="SILVESTAR"):
    return {
        "category": category,
        "is_locomotion": False,
        "speed_mps": 0.0,
        "default_role": "FIXED",
        "label": label,
        "loop": bool(loop),
    }


SILVESTAR_CATALOG = {
    A_IDLE: _meta("Silvestar: sjedi, diše, maše repom (loop)", loop=True),
    A_TALK: _meta("Silvestar: sjedi i priča, maše repom (loop)", loop=True),
    A_LICK: _meta("Silvestar: lizanje na boku (loop)", loop=True),
    A_SHOCK: _meta("Silvestar: lizanje -> šok -> sjedanje"),
    A_JUMP: _meta("Silvestar: skok na podest i sjedanje"),
    A_LEVER: _meta("Silvestar: gurne polugu šapom"),
    A_MASTER: _meta("Silvestar: master izvedba (lizanje, šok, priča, poluga)"),
    A_S02: _meta("Silvestar 02: obilazak ispred kabine (hod, skok)"),
}

WATCH = "Cat_Seated_Watch_Lift (1_120)"

# Gotove kombinacije. "repeat" je broj ponavljanja klipa, "blend" prijelaz u kadrovima.
SILVESTAR_PRESETS = {
    "IDLE": {
        "label": "Idle: sjedi, diše, maše repom",
        "clips": [{"action": A_IDLE, "repeat": 8.0, "blend": 0}],
    },
    "PRICA": {
        "label": "Priča: sjedi i priča",
        "clips": [{"action": A_TALK, "repeat": 6.0, "blend": 0}],
    },
    "IDLE_PRICA_IDLE": {
        "label": "Idle -> priča -> idle",
        "clips": [
            {"action": A_IDLE, "repeat": 1.0, "blend": 0},
            {"action": A_TALK, "repeat": 2.0, "blend": 12},
            {"action": A_IDLE, "repeat": 3.0, "blend": 12},
        ],
    },
    "LIZANJE": {
        "label": "Lizanje (loop)",
        "clips": [{"action": A_LICK, "repeat": 10.0, "blend": 0}],
    },
    "LIZANJE_SOK_IDLE": {
        "label": "Lizanje -> šok -> sjedne -> idle",
        "clips": [
            {"action": A_LICK, "repeat": 2.0, "blend": 0},
            {"action": A_SHOCK, "repeat": 1.0, "blend": 3},
            {"action": A_IDLE, "repeat": 4.0, "blend": 10},
        ],
    },
    "PREDSTAVA": {
        "label": "Predstava: lizanje -> šok -> priča -> idle",
        "clips": [
            {"action": A_LICK, "repeat": 2.0, "blend": 0},
            {"action": A_SHOCK, "repeat": 1.0, "blend": 3},
            {"action": A_TALK, "repeat": 2.0, "blend": 10},
            {"action": A_IDLE, "repeat": 4.0, "blend": 12},
        ],
    },
    "SKOK_IDLE": {
        "label": "Skok na podest -> idle",
        "clips": [
            {"action": A_JUMP, "repeat": 1.0, "blend": 0},
            {"action": A_IDLE, "repeat": 4.0, "blend": 10},
        ],
    },
    "SKOK_PRICA_POLUGA": {
        "label": "Skok -> priča -> poluga -> gleda",
        "clips": [
            {"action": A_JUMP, "repeat": 1.0, "blend": 0},
            {"action": A_TALK, "repeat": 1.0, "blend": 10},
            {"action": A_LEVER, "repeat": 1.0, "blend": 10},
            {"action": WATCH, "repeat": 3.0, "blend": 10},
        ],
    },
    "POLUGA": {
        "label": "Idle -> poluga -> gleda",
        "clips": [
            {"action": A_IDLE, "repeat": 1.0, "blend": 0},
            {"action": A_LEVER, "repeat": 1.0, "blend": 10},
            {"action": WATCH, "repeat": 3.0, "blend": 10},
        ],
    },
    "MASTER": {
        "label": "Master izvedba iz vožnje (cijela)",
        "clips": [{"action": A_MASTER, "repeat": 1.0, "blend": 0}],
    },
    "S02_OBILAZAK": {
        "label": "Silvestar 02: obilazak kabine",
        "clips": [{"action": A_S02, "repeat": 1.0, "blend": 0}],
    },
}

PRESET_ORDER = [
    "IDLE", "PRICA", "IDLE_PRICA_IDLE", "LIZANJE", "LIZANJE_SOK_IDLE", "PREDSTAVA",
    "SKOK_IDLE", "SKOK_PRICA_POLUGA", "POLUGA", "MASTER", "S02_OBILAZAK",
]


# ----------------------------------------------------------------------------
# Datoteka
# ----------------------------------------------------------------------------

def get_silvestar_blend_path() -> str:
    """Put do `silvestar_studio.blend`; po potrebi ga sastavlja iz dijelova `.partNN` iz repozitorija."""
    from .constants import get_studio_root

    roots = [get_studio_root()]
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if here not in roots:
        roots.append(here)
    if bpy.data.filepath:
        roots.append(os.path.dirname(os.path.abspath(bpy.data.filepath)))

    for root in roots:
        path = os.path.join(root, SILVESTAR_BLEND_NAME)
        if os.path.isfile(path) and os.path.getsize(path) > 1_000_000:
            return path
        parts = sorted(glob.glob(path + ".part*"))
        if parts:
            tmp = path + ".assembling"
            try:
                with open(tmp, "wb") as out_f:
                    for p in parts:
                        with open(p, "rb") as in_f:
                            shutil.copyfileobj(in_f, out_f, length=8 * 1024 * 1024)
                os.replace(tmp, path)
                print(f"[Silvestar] Sastavljen {path} iz {len(parts)} dijelova.")
                return path
            except Exception as e:
                print(f"[Silvestar] Ne mogu sastaviti {path}: {e}")
    return os.path.join(roots[0], SILVESTAR_BLEND_NAME)


def _tag_actions():
    for name, meta in SILVESTAR_CATALOG.items():
        act = bpy.data.actions.get(name)
        if not act:
            continue
        act.use_fake_user = True
        act["cat_category"] = meta["category"]
        act["cat_is_locomotion"] = False
        act["cat_speed_mps"] = 0.0
        act["cat_role"] = "FIXED"
        act["cat_label"] = meta["label"]


def ensure_silvestar_actions_loaded() -> list:
    """Učitava Silvestrove akcije u trenutnu datoteku (ako ih još nema). Vraća popis dostupnih."""
    missing = [n for n in SILVESTAR_CATALOG if n not in bpy.data.actions]
    if missing:
        path = get_silvestar_blend_path()
        if os.path.isfile(path):
            try:
                with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
                    data_to.actions = [n for n in missing if n in data_from.actions]
            except Exception as e:
                print(f"[Silvestar] Ne mogu učitati akcije iz {path}: {e}")
        else:
            print(f"[Silvestar] Nema datoteke {path}")
    _tag_actions()
    return [n for n in SILVESTAR_CATALOG if n in bpy.data.actions]


def find_silvestar():
    """Vraća Silvestrov kontroler u sceni (ili None)."""
    obj = bpy.data.objects.get(SILVESTAR_CTRL)
    if obj:
        return obj
    for o in bpy.data.objects:
        if o.get("silvestar_actor"):
            return o
    return None


def append_silvestar(location=(0.0, 0.0, 0.0), rotation_z_deg=0.0):
    """
    Dodaje kolekciju `SILVESTAR` (kontroler, rig, tijelo s krznom) i sve njegove akcije
    u trenutnu scenu. Ako Silvestar već postoji, samo ga vraća.
    """
    import math

    ctrl = find_silvestar()
    if ctrl is None:
        path = get_silvestar_blend_path()
        if not os.path.isfile(path):
            raise FileNotFoundError(f"Nema datoteke {path}. Pokreni: python3 install_cat_studio.py")
        with bpy.data.libraries.load(path, link=False) as (data_from, data_to):
            if SILVESTAR_COLLECTION not in data_from.collections:
                raise RuntimeError(f"U {path} nema kolekcije {SILVESTAR_COLLECTION}")
            data_to.collections = [SILVESTAR_COLLECTION]
            data_to.actions = [n for n in data_from.actions if n not in bpy.data.actions and not n.startswith("PathAnim_")]
        col = data_to.collections[0]
        bpy.context.scene.collection.children.link(col)
        ctrl = find_silvestar()
    ensure_silvestar_actions_loaded()
    if ctrl is not None:
        ctrl.location = location
        ctrl.rotation_euler[2] = math.radians(rotation_z_deg)
    try:
        bpy.context.scene.render.hair_type = "STRIP"
    except Exception:
        pass
    return ctrl


# ----------------------------------------------------------------------------
# Kombinacije
# ----------------------------------------------------------------------------

def list_silvestar_presets() -> list:
    return [(pid, SILVESTAR_PRESETS[pid]["label"]) for pid in PRESET_ORDER]


def apply_silvestar_preset(ctrl=None, preset_id="IDLE", keep_stray_layer=False):
    """
    Slaže gotovu kombinaciju u NLA aktivnog mačka (Silvestra ili bilo kojeg Black Cat mačka).
    Mačak ostaje na mjestu kontrolera; krivulja hoda se odspaja.

    `keep_stray_layer=False` uklanja proceduralni sloj `CAT_Stray_Biomechanics`, jer
    Silvestrovi klipovi već sadrže disanje, treptaje i rep.
    """
    from .rig_actors import find_cat_controller, get_cat_armature_from_ctrl
    from .nla_sequencer import rebuild_cat_nla_sequence_from_specs
    from .constants import STRAY_BIOMECH_TRACK_NAME

    preset = SILVESTAR_PRESETS.get(str(preset_id).upper())
    if not preset:
        return False, f"Nepoznata kombinacija '{preset_id}'. Dostupne: {', '.join(PRESET_ORDER)}"

    if isinstance(ctrl, str):
        ctrl = bpy.data.objects.get(ctrl)
    ctrl = find_cat_controller(ctrl) if ctrl is not None else None
    if ctrl is None:
        ctrl = find_silvestar() or find_cat_controller(bpy.context.active_object)
    if ctrl is None:
        ctrl = append_silvestar()
    if ctrl is None:
        return False, "U sceni nema mačka. Dodaj Silvestra (append_silvestar) ili stvori Black Cat."

    ensure_silvestar_actions_loaded()
    specs = []
    for c in preset["clips"]:
        if c["action"] not in bpy.data.actions:
            if c["action"] == WATCH:
                continue
            return False, f"Nedostaje akcija '{c['action']}' (nema {SILVESTAR_BLEND_NAME}?)"
        specs.append({"action": c["action"], "repeat": c["repeat"], "speed": 1.0, "blend": c["blend"], "mode": "FIXED"})

    # mačak stoji na mjestu kontrolera
    ctrl["cat_attached_curve"] = ""
    ctrl["cat_loop_anim"] = False
    ctrl["cat_frame_offset"] = 0
    if ctrl.animation_data and ctrl.animation_data.action and ctrl.animation_data.action.name.startswith("PathAnim_"):
        ctrl.animation_data.action = None

    ok, msg = rebuild_cat_nla_sequence_from_specs(ctrl, specs, sync_curve=False)
    arm = get_cat_armature_from_ctrl(ctrl)
    if ok and arm and arm.animation_data and not keep_stray_layer:
        for tr in list(arm.animation_data.nla_tracks):
            if tr.name.startswith(STRAY_BIOMECH_TRACK_NAME):
                arm.animation_data.nla_tracks.remove(tr)
    if ok and arm and arm.animation_data:
        end = 1
        for tr in arm.animation_data.nla_tracks:
            for st in tr.strips:
                end = max(end, int(st.frame_end))
        scn = bpy.context.scene
        scn.frame_start = 1
        scn.frame_end = end
    ctrl["silvestar_preset"] = str(preset_id).upper()
    return ok, f"Silvestar: {preset['label']} — {msg}"
