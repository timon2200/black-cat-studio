# AGENTS.md — AI Agent Guide for Black Cat Animation Director Studio v2.0

This document provides complete technical instructions for AI coding and 3D animation agents working with `black_cat_director` in any Blender 4.x / 5.x project.

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
