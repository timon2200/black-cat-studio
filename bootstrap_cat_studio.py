# -*- coding: utf-8 -*-
"""
Black Cat Animation Director Studio v2.0 — Auto-Bootstrap Script
================================================================
Embedded as a Text datablock (`bootstrap_cat_studio.py` with `use_module=True`)
inside `.blend` studio scenes so the `Black Cat Studio` N-Panel (`View3D > Sidebar (N) > Black Cat Studio`)
registers automatically when the file is opened.
"""

import os
import sys
import bpy


def bootstrap():
    candidates = []
    if bpy.data.filepath:
        blend_dir = os.path.dirname(os.path.abspath(bpy.data.filepath))
        candidates.append(blend_dir)
        candidates.append(os.path.join(blend_dir, "black_cat_studio"))

    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(script_dir)
    except Exception:
        pass

    home = os.path.expanduser("~")
    for sub in (
        "black-cat-studio",
        "Documents/black-cat-studio",
        "Desktop/black-cat-studio",
        "black_cat_studio",
        "Documents/black_cat_studio",
    ):
        candidates.append(os.path.join(home, sub))

    for c in candidates:
        if c and os.path.isdir(os.path.join(c, "black_cat_director")):
            if c not in sys.path:
                sys.path.insert(0, c)
            break

    try:
        import black_cat_director as cd
        cd.reload_all_submodules()
        cd.register()
        print("[BlackCatStudio] N-Panel registered (View3D > N > Black Cat Studio).")
    except Exception as e:
        print(f"[BlackCatStudio] Bootstrap warning: {e}")


if __name__ == "__main__":
    bootstrap()
else:
    bootstrap()
