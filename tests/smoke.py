"""Headless smoke test, run inside Blender (no packages beyond what Blender ships):

    blender -b --factory-startup --python-exit-code 1 --python tests/smoke.py
"""
import math
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import bflare  # noqa: E402

# Pure functions
assert bflare._interp([(0, 0), (1, 10)], -1) == 0 and bflare._interp([(0, 0), (1, 10)], 0.5) == 5
for ev in (0.5, 1.0, 3.5):
    # The vignette falloff 1 / (1 + (d / r)^2)^2 at the full-frame corner must lose exactly ev stops.
    d = bflare.FF_CORNER / 18.0 / bflare.vignette_radius(ev)
    assert math.isclose(1.0 / (1.0 + d * d) ** 2, 2.0 ** -ev)
optics = {k: 0.0 for k in bflare.OPTICS_KEYS} | {"blades": 9, "ring_count": 6.0, "cat": 0.5}
for key, spec in bflare.LENSES.items():
    assert set(bflare.lens_values(spec, spec["fmax"], 2 / 3)) <= set(bflare.LENS_NODES), key
    o = optics | bflare.LENS_OPTICS[key] | {"blades": spec["blades"]}
    for k in (bflare.bokeh_kernel(o, 1.0, 1.0), bflare.bokeh_kernel(o, 0.5, -1.0, 0.3, 2.0, 1.0),
              bflare.star_kernel(33, o, 0.7)):
        assert np.isfinite(k).all() and math.isclose(k[..., :3].max(), 1.0, rel_tol=1e-5), key
anamorphic = {"length": 0.35, "thickness": 0.002, "falloff": 2.5, "core": (0.2, 0.45, 1.0),
              "tip": (0.45, 0.25, 1.0), "lines": 3, "spacing": 0.006}
assert np.isfinite(bflare.streak_kernel(anamorphic)).all()

# The add-on against the real Blender API
bflare.register()
try:
    sc = bpy.context.scene
    assert bpy.ops.postfx.build() == {'FINISHED'}
    t = bflare._tree(sc)
    assert t == sc.compositing_node_group and all(t.nodes.get(name) for name, _, _ in bflare.CHAIN)
    for preset in bflare.PRESETS:
        sc.postfx_preset = preset
    for lens in bflare.LENSES:
        sc.postfx_lens = lens
        sc.postfx_fstop = 4.0
    sc.postfx_dof = 'OPTICAL'
    sc.postfx_optics.cat = 0.5  # cat's-eye zones: 8 extra kernels
    bokeh = t.nodes["PF_Bokeh"].node_tree
    assert all(bokeh.nodes[name].image for name, _, _ in bflare.zone_kernels())

    sc.postfx_enabled = False
    assert sc.compositing_node_group is None and bflare._tree(sc) == t
    sc.postfx_enabled = True
    assert sc.compositing_node_group == t

    # Rebuilding keeps the user's values.
    t.nodes["PF_Bloom"].inputs["Strength"].default_value = 0.77
    bpy.ops.postfx.build()
    assert math.isclose(bflare._tree(sc).nodes["PF_Bloom"].inputs["Strength"].default_value, 0.77, rel_tol=1e-6)

    bpy.ops.postfx.remove()
    assert bflare._tree(sc) is None
    assert not [g for g in bpy.data.node_groups if g.name.startswith("PostFX")]
finally:
    bflare.unregister()
print("smoke test passed")
