# AGENTS.md — AI Agent Guide for Black Cat Animation Director Studio v2.0

This document provides complete technical instructions for AI coding and 3D animation agents working with `black_cat_director` in any Blender 4.x / 5.x project.

---

## Silvestar (v2.1)

`silvestar_studio.blend` (repo root, shipped as `.part01` + `.part02`, reassembled by `install_cat_studio.py` or lazily by
`silvestar.get_silvestar_blend_path()`) holds collection `SILVESTAR` (`CTRL_Silvestar` → `ARM_Silvestar` →
`MESH_Silvestar_Body` with `PS_Silvestar_FurCoat`, `MESH_Silvestar_Fur`) plus 8 Silvestar actions and the 36 stock cat actions.
Module: `black_cat_director/silvestar.py`. Requires Blender 5.0+ (layered actions; saved from 5.3).

- **Actions** (`SILVESTAR_CATALOG`, category `SILVESTAR`, all stationary/`FIXED`, 24 fps, frames start at 1):
  `Cat_Silvestar_Sjedi_Idle_Loop` (285 f loop), `Cat_Silvestar_Sjedi_Prica_Loop` (287 f loop),
  `Cat_Silvestar_Lizanje_Loop` (90 f loop), `Cat_Silvestar_Lizanje_Sok_Sjedanje` (164 f),
  `Cat_Silvestar_Skok_Na_Podest` (97 f, root motion on bone `root`, anchored at the END: starts at (−0.33, −0.97, −1.34) m
  relative to the controller, ends at 0), `Cat_Silvestar_Poluga` (97 f), `Cat_Silvestar_Master_Izvedba` (760 f),
  `Cat_Silvestar02_Obilazak_Kabine` (476 f, root motion anchored at the START, ends at (3.08, −0.50, −0.05) m).
  Loop actions have frame N+1 equal to frame 1 (`action.frame_end` = loop length + 1, `use_cyclic`), so NLA `repeat` is seamless.
- **API:** `cd.append_silvestar(location, rotation_z_deg)`, `cd.find_silvestar()`, `cd.ensure_silvestar_actions_loaded()`,
  `cd.list_silvestar_presets()`, `cd.apply_silvestar_preset(ctrl, "IDLE" | "PRICA" | "IDLE_PRICA_IDLE" | "LIZANJE" |
  "LIZANJE_SOK_IDLE" | "PREDSTAVA" | "SKOK_IDLE" | "SKOK_PRICA_POLUGA" | "POLUGA" | "MASTER" | "S02_OBILAZAK")`.
  Operators: `cat_director.silvestar_append`, `cat_director.silvestar_load_clips`, `cat_director.silvestar_preset(preset_id=...)`.
- `apply_silvestar_preset` detaches the cat from its curve, builds the stack with `rebuild_cat_nla_sequence_from_specs`
  and removes the `CAT_Stray_Biomechanics` layer (the clips already contain breathing, blinks and tail). Pass
  `keep_stray_layer=True` to keep it. The clips work on any cat spawned by `cd.spawn_cat` (same rig, same bone names).
- **Do not** re-bake or simplify the Silvestar actions; they are flattened from the production NLA stack and verified
  against it (`database/silvestar_clips.json`, max 0.4 mm on Silvestar 01). To rebuild from the production files:
  `tools/extract_silvestar_samples.py` (run inside the S1 scene) → `tools/build_silvestar_studio.py`.
- Custom sequences: use `cd.set_cat_nla_sequence(ctrl, [...], sync_curve=False)` with `"mode": "FIXED"`. Give loops a
  `repeat` > 1; use `blend` 10–12 frames between seated clips and 3 between `Lizanje_Loop` and `Lizanje_Sok_Sjedanje`
  (the second continues the first on the same frame).
- Test: `Blender -b --factory-startup -P tests/test_silvestar.py`.

---

## 1. Architecture & Directory Structure

```
black-cat-studio/
├── AGENTS.md                        # This AI agent reference guide
├── README.md                        # User & friend installation and workflow guide
├── install_cat_studio.py            # 1-click cross-platform installer & studio .blend builder
├── bootstrap_cat_studio.py          # Auto-registration script for .blend text datablocks
├── black_cat_director_addon.zip     # Standalone Blender Add-on archive
├── database/
│   ├── registry.json                # Metadata for the cat rig & all 29 animations
│   ├── cat_assets_library.blend     # Self-contained asset library (reassembled from .part01 + .part02)
│   ├── cat_assets_library.blend.part01
│   ├── cat_assets_library.blend.part02
│   └── animations_dropin/           # Drop-in folder for custom .blend animation files
├── black_cat_director/              # Blender Add-on & Python SDK package
│   ├── __init__.py                  # bl_info & top-level SDK exports
│   ├── constants.py                 # Portable path resolution, action catalog & presets
│   ├── database.py                  # Automatic lazy-loader & drop-in animation scanner
│   ├── rig_actors.py                # Actor spawner, 180k-strand 3D Fur Coat & Matte-Velvet shader
│   ├── locomotion.py                # 3D Bezier arc-length sampler & zero-slip trajectory solver
│   ├── nla_sequencer.py             # Multi-clip NLA sequencer, NLA Editor sync & Stray biomechanics
│   ├── operators_ui.py              # N-Panel UI (`View3D > N > Black Cat Studio`) & operators
│   └── agent_sdk.py                 # High-level 1-call Python API for agents and scripts
└── tests/
    └── test_cat_studio_workflow.py  # Automated end-to-end verification suite
```

---

## 2. Core Features & Invariants

### A. Furless Viewport / Full 180,000-Strand 3D Fur in Render
- Every spawned cat actor (`CTRL_Cat_01`) has a child body mesh (`MESH_Cat_01_Body`) carrying the **`PS_Cat_FurCoat`** particle hair modifier (`5,000` guide hairs $\times$ `36` interpolated children = `180,000` 3D `STRIP` hair strands driven by `VG_Fur_Density` and `VG_Fur_Length` vertex groups and shaded with `CAT_3D_Fur_Coat_Mat`).
- **Default visibility:**
  - `ps_mod.show_viewport = False` (Furless in the 3D Viewport so animation playback is fast),
  - `ps_mod.show_render = True` (Full 180,000-strand 3D fur coat in F12 / batch renders).
- Use `cd.set_cat_fur_coat("CTRL_Cat_01", viewport_fur=False, render_fur=True, fur_length_m=0.018, fur_children=36)` or `bpy.ops.cat_director.toggle_viewport_fur()` to toggle or customize fur settings.

### B. Matte-Velvet Undercoat, Glossy Golden-Green Eyes & Whiskers
- `cat body` uses an emissive-driven `FUR_FIX_EyeMask` so the cat's golden-green eyes remain wet and glossy (`Roughness = 0.05`, `Specular = 0.85`), while the furred skin is a deep obsidian matte-velvet undercoat (`Roughness = 0.86..0.96`, `Specular = 0.08`, `Coat Weight = 0.0`) with dual-scale anisotropic micro-fur bump (`FUR_FIX_Bump`).
- The 29 facial whisker quads (`116` vertices) use `CAT_Whiskers_Mat` mapped to `UVChannel_1`.

### C. Zero-Slip 3D Curve Locomotion (`locomotion.py`)
- The cat rig faces **`-Y`** in local space (`forward = (0, -1, 0)`). World horizontal tangent `(dx, dy)` maps to `yaw_z = atan2(dx, -dy) + tilt_rad`.
- **Calibrated Stride Speeds (at `scale = 1.0`, `24 FPS`):**
  - `Cat_Walk (1_32)` (`32f`): **`0.32 m/s`** (`0.427 m` per 4-beat stride cycle)
  - `Cat_ slow Run (1_12)` (`12f`): **`0.78 m/s`**
  - `Cat _Run (1_16)` (`16f`): **`1.35 m/s`**
  - `Cat _Jump  (1_27)` (`27f`): **`0.85 m/s`** (with airborne Z arc locked to frames `5..21`)
  - All stationary clips (`Cat idle (1_143)`, `Cat Idle seated (1_144)`, `Cat sitting (1-24)`, `Cat Standing  (1-24)`, `Cat_Seated_Paw_Lick (1_104)`, `Cat_Seated_Paw_Reach (1_72)`, `Cat_Seated_Look_Around (1_120)`, `cat meow FA (1_48)`, `Cat sleeping *`): **`0.00 m/s`** (zero drift along the curve!).
- **`FILL` vs `FIXED` Curve Modes:**
  - In **`FILL`** mode, the solver automatically calculates the strip's `effective_repeat` so the walk covers the remaining curve arc-length at exact stride speed (`0.32 m/s * scale`).
  - In **`FIXED`** mode, the strip plays the exact user-specified `repeat` count and advances along the curve by the exact physical distance `s_cum[tau] = v_stride * t` (`u_hat = s_cum / arc_len`) — guaranteeing **0.00 mm foot sliding** in both `FILL` and `FIXED` modes!

### D. Stacking & Editing Animations in the NLA Editor (`nla_sequencer.py`)
- Use `cd.set_cat_nla_sequence(ctrl, clip_specs)` or `cd.add_cat_nla_clip(ctrl, action_name, repeat, speed, blend, mode)` to stack animations.
- Use `cd.edit_cat_nla_clip(ctrl, index, repeat=..., speed=..., blend=..., mode=...)` to modify any strip in the stack.
- If a user edits NLA strips manually inside Blender's native NLA Editor (`NLA_EDITOR`), call `cd.sync_manual_nla_edits(ctrl)` (or click `Sync Manual NLA Edits` in the N-Panel) to read the manual strip timings and re-solve the zero-slip curve trajectory.
