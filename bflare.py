bl_info = {
    "name": "bflare",
    "author": "origamium",
    "version": (0, 5, 2),
    "blender": (5, 3, 0),
    "location": "3D Viewport > Sidebar > bflare",
    "description": "Post effect chain on the compositor with looks and measured lens profiles",
    "category": "Compositing",
}

import math
from contextlib import contextmanager

import bpy
import numpy as np
from bpy.app.handlers import persistent

# shortcut: uses scene.compositing_node_group (deprecated for 6.0), port when upgrading.
GROUP = "PostFX Lens"
VERSION = 9  # bump whenever the nodes _build creates change, so old chains ask to be rebuilt

# Chain order = list order. (node name, node type or sub-group, fixed values)
CHAIN = [
    ("PF_Exposure", "CompositorNodeExposure", {}),
    ("PF_Bokeh", "PostFX Bokeh", {}),
    ("PF_Star", "PostFX Star", {}),
    ("PF_Streak", "PostFX Streak", {}),
    ("PF_Ghosts", "CompositorNodeGlare", {"Type": "Ghosts", "Quality": "High"}),
    ("PF_Streaks", "CompositorNodeGlare", {"Type": "Streaks", "Quality": "High"}),
    ("PF_Glow", "CompositorNodeGlare", {"Type": "Bloom", "Quality": "High"}),
    ("PF_Bloom", "CompositorNodeGlare", {"Type": "Bloom", "Quality": "High"}),
    ("PF_Lens", "CompositorNodeLensdist", {"Fit": True}),
    ("PF_Squeeze", "PostFX Squeeze", {}),
    ("PF_Vignette", "PostFX Vignette", {}),
    ("PF_Veil", "PostFX Veil", {}),
    ("PF_WB", "CompositorNodeColorBalance", {"Type": "White Point"}),
    ("PF_Grade", "CompositorNodeColorBalance", {"Type": "Lift/Gamma/Gain"}),
    ("PF_Tone", "PostFX Tone", {}),
    ("PF_Grain", "PostFX Grain", {}),
]

# Panel layout: (node name, title, [(socket identifier, label)])
PANEL = [
    ("PF_Exposure", "Exposure", [("Exposure", "Stops")]),
    ("PF_Bloom", "Bloom", [("Strength", "Strength"), ("Threshold", "Threshold"), ("Smoothness", "Knee"),
                           ("Size", "Size"), ("Saturation", "Saturation"), ("Tint", "Tint")]),
    ("PF_Streaks", "Streaks", [("Strength", "Strength"), ("Threshold", "Threshold"), ("Streaks", "Count"),
                               ("Streaks Angle", "Angle"), ("Fade", "Length"),
                               ("Color Modulation", "Dispersion"), ("Tint", "Tint")]),
    ("PF_Ghosts", "Lens Ghosts", [("Strength", "Strength"), ("Threshold", "Threshold"), ("Iterations", "Count"),
                                  ("Color Modulation", "Dispersion"), ("Tint", "Tint")]),
    ("PF_Star", "Diffraction", [("Strength", "Strength"), ("Threshold", "Threshold")]),
    ("PF_Glow", "Aberration Glow", [("Strength", "Strength"), ("Size", "Size"), ("Tint", "Tint")]),
    ("PF_Lens", "Lens", [("Distortion", "Distortion"), ("Dispersion", "Chromatic Aberration")]),
    ("PF_Vignette", "Vignette", [("Intensity", "Intensity"), ("Radius", "Radius")]),
    ("PF_Veil", "Veiling Flare", [("Amount", "Amount")]),
    ("PF_WB", "White Balance", [("Input Temperature", "Temperature"), ("Input Tint", "Tint")]),
    ("PF_Grade", "Color Grade", [("Color Lift", "Shadows"), ("Color Gamma", "Midtones"), ("Color Gain", "Highlights")]),
    ("PF_Tone", "Tone", [("Contrast", "Contrast"), ("Saturation", "Saturation")]),
    ("PF_Grain", "Film Grain", [("Amount", "Amount"), ("Size", "Size")]),
]

W = (1.0, 1.0, 1.0, 1.0)
# Identity values. A preset lists only what differs; nodes it does not mention are switched off.
NEUTRAL = {
    "PF_Exposure": {"Exposure": 0.0},
    "PF_Bloom": {"Strength": 0.0, "Threshold": 1.0, "Smoothness": 0.5, "Size": 0.5, "Saturation": 1.0, "Tint": W},
    "PF_Streaks": {"Strength": 0.0, "Threshold": 4.0, "Smoothness": 0.5, "Streaks": 2, "Streaks Angle": 0.0,
                   "Fade": 0.9, "Color Modulation": 0.25, "Saturation": 1.0, "Tint": W},
    "PF_Ghosts": {"Strength": 0.0, "Threshold": 4.0, "Smoothness": 0.5, "Iterations": 3,
                  "Color Modulation": 0.25, "Saturation": 1.0, "Tint": W},
    "PF_Lens": {"Distortion": 0.0, "Dispersion": 0.0},
    "PF_Vignette": {"Intensity": 0.0, "Radius": 0.6},
    "PF_Glow": {"Strength": 0.0, "Threshold": 0.0, "Smoothness": 0.0, "Size": 0.3, "Saturation": 1.0, "Tint": W},
    "PF_Veil": {"Amount": 0.0},
    "PF_Star": {"Strength": 0.0, "Threshold": 4.0},
    "PF_Streak": {"Strength": 0.0, "Threshold": 3.0},
    "PF_Squeeze": {"Horizontal": 0.0, "Vertical": 0.0},
    "PF_WB": {"Input Temperature": 6500.0, "Input Tint": 10.0},
    "PF_Grade": {"Color Lift": W, "Color Gamma": W, "Color Gain": W},
    "PF_Tone": {"Contrast": 1.0, "Saturation": 1.0},
    "PF_Grain": {"Amount": 0.0, "Size": 1.0},
}

PRESETS = {
    "Neutral": {},
    "Soft Film": {
        "PF_Bloom": {"Strength": 0.12, "Threshold": 1.0, "Smoothness": 1.0, "Size": 0.55},
        "PF_Lens": {"Dispersion": 0.006},
        "PF_Vignette": {"Intensity": 0.35, "Radius": 0.65},
        "PF_WB": {"Input Temperature": 6900.0},
        "PF_Tone": {"Contrast": 1.05, "Saturation": 0.95},
        "PF_Grain": {"Amount": 0.08, "Size": 1.0},
    },
    "Cinematic": {
        "PF_Bloom": {"Strength": 0.18, "Threshold": 1.5, "Smoothness": 0.8, "Size": 0.6},
        "PF_Streaks": {"Strength": 0.2, "Threshold": 6.0, "Streaks": 2, "Fade": 0.93,
                       "Tint": (0.55, 0.75, 1.0, 1.0)},
        "PF_Lens": {"Dispersion": 0.008},
        "PF_Vignette": {"Intensity": 0.35, "Radius": 0.6},
        "PF_Grade": {"Color Lift": (0.996, 1.0, 1.006, 1.0), "Color Gain": (1.04, 1.0, 0.95, 1.0)},
        "PF_Tone": {"Contrast": 1.05, "Saturation": 1.0},
        "PF_Grain": {"Amount": 0.05, "Size": 1.0},
    },
    "Night Neon": {
        "PF_Bloom": {"Strength": 0.28, "Threshold": 1.0, "Smoothness": 1.0, "Size": 0.7, "Saturation": 1.3},
        "PF_Streaks": {"Strength": 0.25, "Threshold": 5.0, "Streaks": 2, "Fade": 0.94,
                       "Tint": (0.6, 0.7, 1.0, 1.0)},
        "PF_Ghosts": {"Strength": 0.06, "Threshold": 8.0, "Iterations": 3, "Color Modulation": 0.5},
        "PF_Lens": {"Dispersion": 0.012},
        "PF_Vignette": {"Intensity": 0.3, "Radius": 0.6},
        "PF_Grade": {"Color Lift": (0.996, 0.999, 1.008, 1.0)},
        "PF_Tone": {"Contrast": 1.05, "Saturation": 1.15},
    },
    "Vintage Lens": {
        "PF_Bloom": {"Strength": 0.22, "Threshold": 0.8, "Smoothness": 1.0, "Size": 0.75},
        "PF_Ghosts": {"Strength": 0.15, "Threshold": 6.0, "Iterations": 4, "Color Modulation": 0.6},
        "PF_Lens": {"Distortion": 0.04, "Dispersion": 0.025},
        "PF_Vignette": {"Intensity": 0.6, "Radius": 0.5},
        "PF_WB": {"Input Temperature": 7400.0},
        "PF_Grade": {"Color Lift": (1.012, 1.006, 0.998, 1.0)},
        "PF_Tone": {"Contrast": 0.95, "Saturation": 0.85},
        "PF_Grain": {"Amount": 0.16, "Size": 1.4},
    },
}


# ---------------------------------------------------------------- lens profiles
#
# Numbers with a lab source are physical: distortion in percent at the frame corner (negative = barrel),
# vignetting in EV at the corner of a 36x24 mm frame per f-stop, lateral colour in percent of image height.
# None means no measured figure was found, and that effect is left off rather than guessed.
# glow / ghosts / veil have no lab unit; they are set by eye from the cited reviews' descriptions.
# Sources: phillipreeve.net and lenstip.com lens reviews, opticallimits.com, imaging-resource.com.

LENSES = {
    "NOCTILUX_095": dict(
        name="Leica Noctilux-M 50mm f/0.95 ASPH", focal=50, fmax=0.95, blades=11, rounded=False, dist=-1.0,
        vig={0.95: 3.5, 1.4: 2.5, 2: 1.8, 2.8: 1.2, 4: 0.6, 5.6: 0.4}, ca=None,
        glow={0.95: 0.6, 1.4: 0.35, 2: 0.15, 2.8: 0.0}, glow_tint=(0.85, 0.72, 1.0, 1.0), ghosts=0.3, veil=0.02,
        note="Distortion sources disagree (-0.1 to -1 %); -1 % used. Coma and cat-eye bokeh not reproduced"),
    "SUMMICRON_50": dict(
        name="Leica Summicron-M 50mm f/2", focal=50, fmax=2.0, blades=8, rounded=True, dist=-0.47,
        vig={2: 2.4, 2.8: 1.33, 4: 0.64, 5.6: 0.44, 8: 0.34}, ca=None,
        glow=None, ghosts=0.08, veil=0.005,
        note="Lateral colour not measured, left off"),
    "SUMMILUX_35_PRE": dict(
        name="Leica Summilux-M 35mm f/1.4 pre-ASPH", focal=35, fmax=1.4, blades=10, rounded=False, dist=None,
        vig=None, ca=None,
        glow={1.4: 0.9, 2: 0.15, 2.8: 0.0}, ghosts=0.3, veil=0.04,
        note="Glow only: no measured distortion or vignetting exists, both left off. Swirl not reproduced"),
    "NOCT_NIKKOR_58": dict(
        name="Nikon Noct-Nikkor 58mm f/1.2", focal=58, fmax=1.2, blades=9, rounded=False, dist=-1.33,
        vig={1.2: 2.4, 2: 1.4, 2.8: 0.5, 4: 0.2}, ca=None,
        glow={1.2: 0.15, 2: 0.0}, ghosts=0.5, veil=0.03,
        note="Later 9-blade version. Lateral colour not measured, left off"),
    "NIKKOR_105_25": dict(
        name="Nikon Nikkor 105mm f/2.5", focal=105, fmax=2.5, blades=7, rounded=False, dist=None,
        vig={2.5: 1.5, 2.8: 1.2, 4: 0.4, 5.6: 0.1}, ca=0.038,
        glow=None, ghosts=0.0, veil=0.03,
        note="Distortion not measured (reported as marginal barrel), left off"),
    "NIKKOR_58_14G": dict(
        name="Nikon AF-S Nikkor 58mm f/1.4G", focal=58, fmax=1.4, blades=9, rounded=True, dist=-1.41,
        vig={1.4: 1.42, 2: 0.8, 2.8: 0.31}, ca=0.055,
        glow={1.4: 0.4, 2: 0.15, 2.8: 0.0}, glow_tint=(1.0, 0.8, 0.9, 1.0), ghosts=0.05, veil=0.02,
        note="Coma and cat-eye bokeh not reproduced"),
    "CANON_DREAM_095": dict(
        name="Canon 50mm f/0.95 Dream Lens", focal=50, fmax=0.95, blades=10, rounded=True, dist=None,
        vig={0.95: 4.2, 1.4: 3.5, 2: 2.5, 2.8: 2.0, 4: 1.6, 5.6: 1.5, 8: 1.4}, ca=None,
        glow={0.95: 1.0, 1.4: 0.2, 2: 0.05, 2.8: 0.0}, glow_tint=(0.85, 0.72, 1.0, 1.0), ghosts=0.7, veil=0.06,
        note="Vignetting from a modified TV-version sample. Distortion not measured (reported as strong barrel), left off"),
    "CANON_85_12L": dict(
        name="Canon EF 85mm f/1.2L II USM", focal=85, fmax=1.2, blades=8, rounded=True, dist=-1.03,
        vig={1.2: 2.1, 1.4: 1.62, 2: 0.72, 2.8: 0.15}, ca=0.021,
        glow=None, ghosts=0.0, veil=0.005,
        note="Flare behaviour not documented, left off"),
    "OTUS_55": dict(
        name="Zeiss Otus 55mm f/1.4", focal=55, fmax=1.4, blades=9, rounded=True, dist=-0.69,
        vig={1.4: 2.05, 2: 1.41, 2.8: 0.69, 4: 0.28}, ca=None,
        glow=None, ghosts=0.0, veil=0.0,
        note="The clean reference: aberrations corrected, almost no flare"),
    "PANAVISION_C50": dict(
        name="Panavision C-Series 50mm anamorphic", focal=50, fmax=2.3, blades=0, rounded=True, dist=None,
        vig=None, ca=None, ratio=2.0,
        glow=None, ghosts=0.1, veil=0.04, streaks=(0.6, (0.15, 0.4, 1.0, 1.0)),
        note="Character only: no lab data exists. Oval bokeh and blue streaks; distortion and the 2x squeeze field "
             "of view are left off (set them under Anamorphic)"),
    "HELIOS_44_2": dict(
        name="Helios 44-2 58mm f/2", focal=58, fmax=2.0, blades=8, rounded=False, dist=None,
        vig=None, ca=None,
        glow={2: 0.3, 2.8: 0.0}, ghosts=0.3, veil=0.04,
        note="Swirl from mechanical vignetting plus overcorrected bokeh (needs Optical depth of field). "
             "No lab data for this variant: distortion and vignetting left off"),
}

# Bokeh character per lens for the optical depth of field, set by eye from the cited reviews
# (outlined or smooth highlights, bokeh fringing, cat-eye). sa: >0 smooth background, <0 outlined.
LENS_OPTICS = {
    "NOCTILUX_095": dict(sa=-0.12, loca=0.03, cat=0.8),
    "SUMMICRON_50": dict(sa=0.0, loca=0.01, cat=0.4),
    "SUMMILUX_35_PRE": dict(sa=-0.2, loca=0.025, cat=0.7),
    "NOCT_NIKKOR_58": dict(sa=0.1, loca=0.02, cat=0.6),
    "NIKKOR_105_25": dict(sa=0.2, loca=0.04, cat=0.4),
    "NIKKOR_58_14G": dict(sa=0.3, loca=0.03, cat=0.7, rings=0.08),
    "CANON_DREAM_095": dict(sa=-0.2, loca=0.04, cat=0.9),
    "CANON_85_12L": dict(sa=0.2, loca=0.03, cat=0.6),
    "OTUS_55": dict(sa=0.0, loca=0.0025, cat=0.5),
    "PANAVISION_C50": dict(sa=0.0, loca=0.01, cat=0.3),
    "HELIOS_44_2": dict(sa=-0.25, loca=0.02, cat=1.0),
}

FF_CORNER = 21.63  # mm from the centre to the corner of a 36x24 mm frame

# Measured in Blender 5.3 on the Lens Distortion node with Fit on:
# (radial distortion at the frame corner in percent, Distortion socket value).
_DIST_TABLE = [(-28.2, 0.2), (-16.5, 0.1), (-9.01, 0.05), (-3.82, 0.02), (-1.95, 0.01), (0.0, 0.0),
               (1.986, -0.01), (3.97, -0.02), (9.99, -0.05), (20.33, -0.1), (43.2, -0.2)]
_CA_PER_UNIT = 29.5  # measured: red-blue separation in percent of image height per unit of Dispersion
_GLOW_GAIN, _GHOST_GAIN = 0.5, 0.25


def _interp(pairs, x):
    """Piecewise-linear lookup in [(x, y)] sorted by x, clamped at both ends."""
    if x <= pairs[0][0]:
        return pairs[0][1]
    for (x0, y0), (x1, y1) in zip(pairs, pairs[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pairs[-1][1]


def _at_stop(table, fstop):
    """Value of a {f-number: value} table at fstop, interpolated in stops."""
    if not table:
        return 0.0
    return _interp(sorted((math.log2(n), v) for n, v in table.items()), math.log2(fstop))


def vignette_radius(ev):
    """Radius of the PostFX Vignette falloff that loses ev stops at the full-frame corner."""
    return (FF_CORNER / 18.0) / math.sqrt(2.0 ** (ev / 2.0) - 1.0)


def lens_values(spec, fstop, aspect):
    """Node values for a lens at an f-stop. aspect = short side / long side of the render."""
    corner = 18.0 * math.hypot(1.0, aspect)
    v = {}
    k = _interp(_DIST_TABLE, spec["dist"] * (corner / FF_CORNER) ** 2) if spec["dist"] else 0.0
    d = spec["ca"] / _CA_PER_UNIT if spec["ca"] else 0.0
    if k or d:
        v["PF_Lens"] = {"Distortion": k, "Dispersion": d}
    ev = _at_stop(spec["vig"], fstop)
    if ev > 0.01:
        v["PF_Vignette"] = {"Intensity": 1.0, "Radius": vignette_radius(ev)}
    glow = _at_stop(spec["glow"], fstop)
    if glow > 0.0:
        v["PF_Glow"] = {"Strength": min(1.0, glow * _GLOW_GAIN), "Tint": spec.get("glow_tint", W)}
    if spec["ghosts"]:
        v["PF_Ghosts"] = {"Strength": spec["ghosts"] * _GHOST_GAIN, "Threshold": 8.0, "Color Modulation": 0.5}
    if spec.get("streaks"):
        v["PF_Streak"] = {"Strength": spec["streaks"][0], "Threshold": 3.0}
    if spec["veil"]:
        v["PF_Veil"] = {"Amount": spec["veil"]}
    # The diffraction pattern comes from the iris shape, so spikes only appear once the blades close in.
    # About a tenth of the light of a point lands outside the Airy core.
    v["PF_Star"] = {"Strength": 0.1, "Threshold": 4.0}
    return v


LENS_NODES = ("PF_Lens", "PF_Vignette", "PF_Glow", "PF_Ghosts", "PF_Streaks", "PF_Veil", "PF_Star", "PF_Streak", "PF_Squeeze")


# ---------------------------------------------------------------- node helpers

def _sock(node, key):
    for s in node.inputs:
        if s.identifier == key:
            return s
    return node.inputs.get(key)


def _set(node, values):
    for key, v in values.items():
        s = _sock(node, key)
        if s is not None:
            s.default_value = v


def _new_group(name, inputs):
    """inputs: [(name, default, min, max)]. Image in/out sockets are added automatically."""
    g = bpy.data.node_groups.new(name, "CompositorNodeTree")
    g.interface.new_socket("Image", in_out='OUTPUT', socket_type='NodeSocketColor')
    g.interface.new_socket("Image", in_out='INPUT', socket_type='NodeSocketColor')
    for n, d, lo, hi in inputs:
        s = g.interface.new_socket(n, in_out='INPUT', socket_type='NodeSocketFloat')
        s.default_value, s.min_value, s.max_value = d, lo, hi
    return g, g.nodes.new("NodeGroupInput"), g.nodes.new("NodeGroupOutput")


def _feed(g, sock, v):
    """Set a constant on an input socket, or link an output socket into it."""
    if isinstance(v, (int, float)):
        sock.default_value = v
    else:
        g.links.new(v, sock)


def _math(g, op, a, b=None):
    n = g.nodes.new("ShaderNodeMath")
    n.operation = op
    for i, v in enumerate((a, b)):
        if v is not None:
            _feed(g, n.inputs[i], v)
    return n.outputs[0]


def _mix(g, fac, a, b, blend='MIX'):
    n = g.nodes.new("ShaderNodeMix")
    n.data_type, n.blend_type = 'RGBA', blend
    _feed(g, n.inputs[0], fac)
    # The Mix node keeps float, vector and colour sockets side by side; 6, 7 and 2 are the colour ones.
    g.links.new(a, n.inputs[6])
    g.links.new(b, n.inputs[7])
    return n.outputs[2]


def _multiply(g, image, factor):
    return _mix(g, 1.0, image, factor, 'MULTIPLY')


def _size(g, image):
    """Width and height of an image, as sockets."""
    info = g.nodes.new("CompositorNodeImageInfo")
    g.links.new(image, info.inputs[0])
    dim = g.nodes.new("ShaderNodeSeparateXYZ")
    g.links.new(info.outputs["Dimensions"], dim.inputs[0])
    return dim.outputs[0], dim.outputs[1]


def _scale(g, sock, factor):
    n = g.nodes.new("CompositorNodeScale")
    n.inputs["Type"].default_value = "Relative"
    for axis in ("X", "Y"):
        _feed(g, n.inputs[axis], factor)
    # Clip would sample black past the border and darken the outermost pixels.
    n.inputs["Extension X"].default_value = n.inputs["Extension Y"].default_value = "Extend"
    g.links.new(sock, n.inputs["Image"])
    return n.outputs[0]


def _star():
    return _kernel_glare("PostFX Star", "K_Star", 4.0)


def _streak():
    return _kernel_glare("PostFX Streak", "K_Streak", 3.0)


def _kernel_glare(name, kernel, threshold):
    # Glare from a computed kernel, on a STAR_RES-wide copy and added back at full size: its cost and its
    # size on screen are then the same in the viewport and in the render.
    g, gi, go = _new_group(name, [("Strength", 0.0, 0.0, 1.0), ("Threshold", threshold, 0.0, 1e4)])
    # The glare node normalises each colour channel of the kernel on its own, so colour is applied after it.
    tint = g.interface.new_socket("Tint", in_out='INPUT', socket_type='NodeSocketColor')
    tint.default_value = (1.0, 1.0, 1.0, 1.0)
    down = _math(g, 'MINIMUM', _math(g, 'DIVIDE', STAR_RES, _math(g, 'MAXIMUM', *_size(g, gi.outputs["Image"]))), 1.0)
    glare = g.nodes.new("CompositorNodeGlare")
    _set(glare, {"Type": "Kernel", "Quality": "High", "Kernel Data Type": "Color", "Smoothness": 0.5})
    g.links.new(_scale(g, gi.outputs["Image"], down), glare.inputs["Image"])
    g.links.new(gi.outputs["Strength"], glare.inputs["Strength"])
    g.links.new(gi.outputs["Threshold"], _sock(glare, "Highlights Threshold"))
    k = g.nodes.new("CompositorNodeImage")
    k.name = kernel
    g.links.new(k.outputs[0], _sock(glare, "Color Kernel"))
    glow = _multiply(g, glare.outputs["Glare"], gi.outputs["Tint"])
    glow = _scale(g, glow, _math(g, 'DIVIDE', 1.0, down))
    g.links.new(_mix(g, 1.0, gi.outputs["Image"], glow, 'ADD'), go.inputs["Image"])
    return g


def _squeeze():
    """Separate horizontal and vertical radial distortion: anamorphic lenses bow lines differently along
    each axis (typically barrel across, pincushion up and down, which widens faces in the middle).
    Values are percent at the corner of a 36x24 mm frame, negative = barrel, as in the lens table."""
    g, gi, go = _new_group("PostFX Squeeze", [("Horizontal", 0.0, -30.0, 30.0), ("Vertical", 0.0, -30.0, 30.0)])
    co = g.nodes.new("CompositorNodeImageCoordinates")
    g.links.new(gi.outputs["Image"], co.inputs["Image"])
    uv = g.nodes.new("ShaderNodeSeparateXYZ")
    g.links.new(co.outputs["Uniform"], uv.inputs[0])
    u, v = uv.outputs[0], uv.outputs[1]
    w, h = _size(g, gi.outputs["Image"])
    longest = _math(g, 'MAXIMUM', w, h)
    aspect = _math(g, 'DIVIDE', _math(g, 'MINIMUM', w, h), longest)
    rc2 = (FF_CORNER / 18.0) ** 2
    kx = _math(g, 'MULTIPLY', gi.outputs["Horizontal"], -0.01 / rc2)
    ky = _math(g, 'MULTIPLY', gi.outputs["Vertical"], -0.01 / rc2)
    r2 = _math(g, 'ADD', _math(g, 'MULTIPLY', u, u), _math(g, 'MULTIPLY', v, v))
    # Zoom in just enough that barrel distortion never samples past the frame corner.
    fit = _math(g, 'ADD', 1.0, _math(g, 'MULTIPLY', _math(g, 'MAXIMUM', _math(g, 'MAXIMUM', kx, ky), 0.0),
                                     _math(g, 'ADD', 1.0, _math(g, 'MULTIPLY', aspect, aspect))))
    half = _math(g, 'MULTIPLY', longest, 0.5)
    disp = g.nodes.new("ShaderNodeCombineXYZ")
    for axis, (c, k) in enumerate(((u, kx), (v, ky))):
        source = _math(g, 'DIVIDE', _math(g, 'MULTIPLY', c, _math(g, 'ADD', 1.0, _math(g, 'MULTIPLY', k, r2))), fit)
        # Displace shows, at each pixel p, the input at p - displacement (in pixels).
        g.links.new(_math(g, 'MULTIPLY', _math(g, 'SUBTRACT', c, source), half), disp.inputs[axis])
    d = g.nodes.new("CompositorNodeDisplace")
    d.inputs["Extension X"].default_value = d.inputs["Extension Y"].default_value = "Extend"
    g.links.new(gi.outputs["Image"], d.inputs["Image"])
    g.links.new(disp.outputs[0], d.inputs["Displacement"])
    g.links.new(d.outputs[0], go.inputs["Image"])
    return g


def _vignette():
    # Natural falloff: 1 / (1 + (d / radius)^2)^2, blended in by Intensity.
    g, gi, go = _new_group("PostFX Vignette", [("Intensity", 0.0, 0.0, 1.0), ("Radius", 0.6, 0.1, 20.0)])
    co = g.nodes.new("CompositorNodeImageCoordinates")
    g.links.new(gi.outputs["Image"], co.inputs["Image"])
    ln = g.nodes.new("ShaderNodeVectorMath")
    ln.operation = 'LENGTH'
    g.links.new(co.outputs["Uniform"], ln.inputs[0])
    x = _math(g, 'DIVIDE', ln.outputs["Value"], gi.outputs["Radius"])
    fall = _math(g, 'DIVIDE', 1.0, _math(g, 'POWER', _math(g, 'ADD', _math(g, 'POWER', x, 2.0), 1.0), 2.0))
    k = _math(g, 'ADD', 1.0, _math(g, 'MULTIPLY', gi.outputs["Intensity"], _math(g, 'SUBTRACT', fall, 1.0)))
    g.links.new(_multiply(g, gi.outputs["Image"], k), go.inputs["Image"])
    return g


def _veil():
    # Veiling flare: a fraction of all the light in the frame is scattered evenly over the image.
    g, gi, go = _new_group("PostFX Veil", [("Amount", 0.0, 0.0, 1.0)])
    lv = g.nodes.new("CompositorNodeLevels")
    g.links.new(gi.outputs["Image"], lv.inputs["Image"])
    g.links.new(_mix(g, gi.outputs["Amount"], gi.outputs["Image"], lv.outputs["Mean"]), go.inputs["Image"])
    return g


def _tone():
    # Contrast pivots on middle grey (0.18) in scene-linear, then saturation.
    g, gi, go = _new_group("PostFX Tone", [("Contrast", 1.0, 0.5, 2.0), ("Saturation", 1.0, 0.0, 2.0)])
    sep = g.nodes.new("CompositorNodeSeparateColor")
    com = g.nodes.new("CompositorNodeCombineColor")
    g.links.new(gi.outputs["Image"], sep.inputs[0])
    for i in range(3):
        v = _math(g, 'MAXIMUM', _math(g, 'DIVIDE', sep.outputs[i], 0.18), 0.0)
        g.links.new(_math(g, 'MULTIPLY', _math(g, 'POWER', v, gi.outputs["Contrast"]), 0.18), com.inputs[i])
    g.links.new(sep.outputs[3], com.inputs[3])
    hs = g.nodes.new("CompositorNodeHueSat")
    g.links.new(com.outputs[0], hs.inputs["Image"])
    g.links.new(gi.outputs["Saturation"], hs.inputs["Saturation"])
    g.links.new(hs.outputs[0], go.inputs["Image"])
    return g


def _grain():
    # Per-pixel white noise, softened by Size, new pattern every frame. Multiplicative, so blacks stay clean.
    g, gi, go = _new_group("PostFX Grain", [("Amount", 0.0, 0.0, 1.0), ("Size", 1.0, 0.5, 4.0)])
    co = g.nodes.new("CompositorNodeImageCoordinates")
    g.links.new(gi.outputs["Image"], co.inputs["Image"])
    tm = g.nodes.new("CompositorNodeSceneTime")
    wn = g.nodes.new("ShaderNodeTexWhiteNoise")
    wn.noise_dimensions = '4D'
    g.links.new(co.outputs["Pixel"], wn.inputs["Vector"])
    g.links.new(tm.outputs["Frame"], wn.inputs["W"])
    size = g.nodes.new("ShaderNodeCombineXYZ")
    radius = _math(g, 'SUBTRACT', gi.outputs["Size"], 0.5)
    g.links.new(radius, size.inputs[0])
    g.links.new(radius, size.inputs[1])
    bl = g.nodes.new("CompositorNodeBlur")
    g.links.new(wn.outputs["Value"], bl.inputs["Image"])
    g.links.new(size.outputs[0], bl.inputs["Size"])
    sep = g.nodes.new("CompositorNodeSeparateColor")
    g.links.new(bl.outputs[0], sep.inputs[0])
    # Blurring lowers the noise contrast; scale it back up with Size.
    gain = _math(g, 'MULTIPLY', _math(g, 'MULTIPLY', gi.outputs["Amount"], 2.0), gi.outputs["Size"])
    k = _math(g, 'ADD', 1.0, _math(g, 'MULTIPLY', _math(g, 'SUBTRACT', sep.outputs[0], 0.5), gain))
    g.links.new(_multiply(g, gi.outputs["Image"], k), go.inputs["Image"])
    return g


# ---------------------------------------------------------------- optics: point spread functions
#
# Everything here works on the exit pupil. Pupil coordinates are in units of the current iris:
# the iris polygon has an inscribed radius of 1 and the lens barrel has a radius of 1 / stop,
# where stop = max aperture / f-number (1 = wide open).

KERNEL = 64  # bokeh kernel resolution in pixels (the blur runs at half resolution)


def _aperture(u, v, stop, blades, curvature, rotation, cat=None, obstruction=0.0):
    """Transmission mask of the pupil: barrel, iris blades, mechanical vignetting, central obstruction."""
    rho = np.hypot(u, v)
    a = rho <= 1.0 / stop
    if blades >= 3:
        seg = 2.0 * math.pi / blades
        edge = 1.0 / np.cos(np.mod(np.arctan2(v, u) - rotation, seg) - seg / 2.0)
        round_edge = 1.0 / math.sqrt(math.cos(math.pi / blades))
        a &= rho <= edge * (1.0 - curvature) + round_edge * curvature
    else:
        a &= rho <= 1.0
    if cat is not None:
        # Front and rear openings of the barrel's size, displaced to either side for an off-axis point,
        # clip the pupil into a cat's eye. A stopped-down iris fits between them and stays whole.
        cx, cy = 0.5 * cat[0] / stop, 0.5 * cat[1] / stop
        a &= (np.hypot(u - cx, v - cy) <= 1.0 / stop) & (np.hypot(u + cx, v + cy) <= 1.0 / stop)
    if obstruction > 0.0:
        a &= rho >= obstruction / stop
    return a


def _kernel_half(o, stop):
    """Half-width of the bokeh kernel in units of the circle of confusion radius."""
    half = 1.0
    if o["blades"] >= 3 and stop < 1.0:
        half = min(1.0 / math.cos(math.pi / o["blades"]), 1.0 / stop)
    return half * (1.0 + o["loca"])


def bokeh_kernel(o, stop, side, cat_angle=None, ratio=1.0, field=1.0):
    """Geometric point spread function of a defocused point.

    Rays through the pupil at radius p land at r = p (1 + s p^2) / (1 + s): defocus plus third-order
    spherical aberration. The intensity is the pupil transmission times the ray density p dp / (r dr).
    side = +1 behind the focus plane, -1 in front, where the aberration acts with the opposite sign.
    """
    ss = 3
    n = KERNEL * ss
    half = _kernel_half(o, stop)
    ax = (np.arange(n) + 0.5) / n * 2.0 - 1.0
    x, y = np.meshgrid(ax * half * ratio, ax * half)
    dist = np.maximum(np.hypot(x, y), 1e-9)
    rho_max = half * 1.05
    # Spherical aberration grows with the square of the aperture radius, so it fades when stopped down.
    s = max(o["sa"] * side * stop * stop, -0.3 / (rho_max * rho_max))
    rho_t = np.linspace(0.0, rho_max, 4096)
    r_t = rho_t * (1.0 + s * rho_t * rho_t) / (1.0 + s)
    cat = None
    if cat_angle is not None and o["cat"] > 0.0:
        # field = image height as a fraction of the full-frame corner; the clipping grows linearly with it.
        cat = (o["cat"] * field * math.cos(cat_angle), o["cat"] * field * math.sin(cat_angle))
    out = np.zeros((KERNEL, KERNEL, 4), np.float32)
    for c, colour in enumerate((-1.0, 1.0, -1.0)):
        # Axial colour: green focuses apart from red and blue, so its disc is larger behind and smaller in front.
        scale = 1.0 + o["loca"] * colour * side
        r = dist / scale
        rho = np.interp(r, r_t, rho_t, right=1e6)
        mask = _aperture(rho * x / dist, rho * y / dist, stop, o["blades"], o["curvature"], o["rotation"],
                         cat, o["obstruction"])
        full = (rho * stop) ** 2
        trans = np.exp(-o["apodization"] * full) * (1.0 + o["rings"] * np.cos(2.0 * math.pi * o["ring_count"] * full))
        density = (1.0 + s) ** 2 / ((1.0 + s * rho * rho) * (1.0 + 3.0 * s * rho * rho))
        img = np.where(mask, trans * density, 0.0).reshape(KERNEL, ss, KERNEL, ss).mean((1, 3))
        out[..., c] = img / max(img.sum(), 1e-12)
    # Equal energy per colour, then scaled so the peak is 1: the Bokeh Blur node ignores very small weights.
    out[..., :3] /= max(out[..., :3].max(), 1e-12)
    out[..., 3] = out[..., 1]  # the blur filters alpha with the kernel's alpha, and alpha carries the layer mask
    return out


def star_kernel(size, o, stop):
    """Fraunhofer diffraction pattern of the iris: |FFT(pupil)|^2 per colour, with the Airy core removed.

    The shape is physical (N blades give N or 2N spikes, red reaches further than blue). The scale is not:
    at real pixel sizes the pattern is far smaller than a pixel, so it is enlarged to be visible.
    """
    m = 128
    while m < size:
        m *= 2
    ss = 2
    out = np.zeros((size, size, 4), np.float32)
    yy, xx = np.mgrid[0:size, 0:size] - size // 2
    dist = np.hypot(xx, yy)
    ax = (np.arange(m * ss) + 0.5) / ss - m / 2.0
    lo = m // 2 - size // 2
    edge = np.clip((1.0 - dist / (size / 2.0)) * 4.0, 0.0, 1.0)
    for c, centre in enumerate((0.61, 0.54, 0.46)):
        acc = np.zeros((size, size))
        # Real light is a continuous spectrum: integrating over each colour band smears the Airy rings
        # into a smooth halo and leaves the spikes.
        for wavelength in centre * np.linspace(0.85, 1.15, 5):
            diameter = 48.0 * 0.54 / wavelength
            u, v = np.meshgrid(ax / (diameter / 2.0), ax / (diameter / 2.0))
            mask = _aperture(u, v, stop, o["blades"], o["curvature"], o["rotation"]).astype(np.float32)
            psf = np.abs(np.fft.fftshift(np.fft.fft2(mask.reshape(m, ss, m, ss).mean((1, 3))))) ** 2
            acc += psf[lo:lo + size, lo:lo + size] / psf.sum()
        # Drop the Airy core (it is the image itself); same radius for every colour, set by the longest wavelength.
        airy = 1.22 * m / (48.0 * 0.54 / (0.61 * 1.15))
        acc *= np.clip((dist - 1.5 * airy) / (1.5 * airy), 0.0, 1.0) * edge
        out[..., c] = acc / max(acc.sum(), 1e-12)
    out[..., :3] /= max(out[..., :3].max(), 1e-12)
    out[..., 3] = 1.0
    return out


ANAMORPHIC_KEYS = ("length", "thickness", "falloff", "core", "tip", "lines", "spacing")


def streak_kernel(a):
    """Horizontal flare streak of an anamorphic lens: light scattered sideways by the cylindrical elements.

    Brightness falls along the streak as (1 - x/L)^falloff, the colour shifts from the core colour to the tip
    colour, and the vertical profile is gaussian. Several parallel lines can be stacked, fainter outwards.
    Sizes are fractions of the image width.
    """
    length = max(a["length"] * STAR_RES, 2.0)
    sigma = max(a["thickness"] * STAR_RES, 0.4)
    spacing = a["spacing"] * STAR_RES
    offsets = [(i - (a["lines"] - 1) / 2.0) * spacing for i in range(a["lines"])]
    half_h = int(math.ceil(3.0 * sigma + max(abs(o) for o in offsets)))
    half_w = int(math.ceil(length))
    x = np.arange(-half_w, half_w + 1, dtype=np.float64)
    y = np.arange(-half_h, half_h + 1, dtype=np.float64)[:, None]
    t = np.minimum(np.abs(x) / length, 1.0)
    along = (1.0 - t) ** a["falloff"]
    across = np.zeros((y.shape[0], 1))
    for i, off in enumerate(offsets):
        weight = 1.0 / (1.0 + abs(i - (a["lines"] - 1) / 2.0))
        across += weight * np.exp(-0.5 * ((y - off) / sigma) ** 2)
    out = np.zeros((y.shape[0], x.shape[0], 4), np.float32)
    shade = t ** 0.7
    for c in range(3):
        # Only the shift from core to tip lives in the kernel; the core colour is applied as the tint.
        colour = (1.0 - shade) + shade * a["tip"][c] / max(a["core"][c], 1e-3)
        out[..., c] = across * (along * colour)[None, :]
    out[..., :3] /= max(out[..., :3].max(), 1e-12)
    out[..., 3] = 1.0
    return out


def _image(name, arr):
    h, w = arr.shape[:2]
    img = bpy.data.images.get(name)
    if img is not None and tuple(img.size) != (w, h):
        bpy.data.images.remove(img)
        img = None
    if img is None:
        img = bpy.data.images.new(name, w, h, alpha=True, float_buffer=True, is_data=True)
    img.pixels.foreach_set(np.ascontiguousarray(arr, np.float32).ravel())
    # Not img.update(): that builds an 8-bit display buffer, which the compositor then reads instead of the floats.
    img.gl_free()
    img.update_tag()
    return img


ZONES = 4  # cat's-eye directions over half a turn; the clipped pupil looks the same rotated by 180 degrees
RINGS = (0.5, 1.0)  # image heights (fraction of the full-frame corner) that get their own set of kernels
# The blur and the diffraction glare run on a small buffer of fixed width, whatever the output size: the
# cost of a gather blur grows with pixels times radius squared, so on a Retina viewport it would otherwise
# grow with the fourth power of the width. The depth of field gets separate widths for the viewport and
# the final render (set in the panel); the diffraction pattern uses one width so it has the same size in both.
STAR_RES = 480.0


def zone_kernels():
    """(image node name, ring index or None for the centre, direction index) for every far kernel."""
    return [("K_Far", None, 0)] + [("K_Far_%d_%d" % (j, i), j, i) for j in range(len(RINGS)) for i in range(ZONES)]


OPTICS_KEYS = ("blades", "curvature", "rotation", "sa", "loca", "cat", "rings", "ring_count",
               "apodization", "obstruction")


def _rebuild_bokeh(g, zones):
    """Depth-driven blur: circle of confusion from the thin-lens equation, then one blur behind and one in front."""
    g.nodes.clear()
    gi, go = g.nodes.new("NodeGroupInput"), g.nodes.new("NodeGroupOutput")
    inp = gi.outputs

    def image_node(name):
        n = g.nodes.new("CompositorNodeImage")
        n.name = name
        return n.outputs[0]

    def blur(image, kernel, size):
        n = g.nodes.new("CompositorNodeBokehBlur")
        g.links.new(image, n.inputs["Image"])
        g.links.new(kernel, n.inputs["Bokeh"])
        g.links.new(size, n.inputs["Size"])
        return n.outputs[0]

    def scale(sock, factor):
        return _scale(g, sock, factor)

    def channel(image):
        n = g.nodes.new("CompositorNodeSeparateColor")
        g.links.new(image, n.inputs[0])
        return n.outputs[0]

    def mix(fac, a, b, blend='MIX'):
        return _mix(g, fac, a, b, blend)

    def ramp(px):
        # 0 below half a pixel of blur, 1 from two pixels: there the low-resolution blur takes over.
        return _math(g, 'MINIMUM', _math(g, 'MAXIMUM', _math(g, 'DIVIDE', _math(g, 'SUBTRACT', px, 0.5), 1.5), 0.0), 1.0)

    width = _math(g, 'MAXIMUM', *_size(g, inp["Image"]))
    f = _math(g, 'DIVIDE', inp["Focal"], 1000.0)
    sensor = _math(g, 'DIVIDE', inp["Sensor"], 1000.0)
    # Radius in pixels: 0.5 f^2 / (N (s - f)) * (z - s) / z, as a fraction of the sensor width.
    k = _math(g, 'DIVIDE', _math(g, 'MULTIPLY', _math(g, 'MULTIPLY', f, f), 0.5),
              _math(g, 'MULTIPLY', inp["F-Stop"], _math(g, 'SUBTRACT', inp["Focus"], f)))
    k = _math(g, 'MULTIPLY', _math(g, 'DIVIDE', k, sensor), width)
    # The depth pass is not anti-aliased, so the soft outline of a near object carries the depth of what is
    # behind it. Pull depth edges two pixels towards the camera so those outlines stay with their object.
    edge = g.nodes.new("CompositorNodeDilateErode")
    edge.inputs["Size"].default_value = -2
    g.links.new(inp["Depth"], edge.inputs["Mask"])
    depth = edge.outputs[0]
    signed = _math(g, 'MULTIPLY', k, _math(g, 'DIVIDE', _math(g, 'SUBTRACT', depth, inp["Focus"]), depth))
    cap = _math(g, 'MULTIPLY', inp["Max Radius"], width)
    signed = _math(g, 'MINIMUM', _math(g, 'MAXIMUM', signed, _math(g, 'MULTIPLY', cap, -1.0)), cap)
    is_render = g.nodes.new("ShaderNodeMath")
    is_render.operation = 'COMPARE'
    g.links.new(width, is_render.inputs[0])
    g.links.new(inp["Render Width"], is_render.inputs[1])
    is_render.inputs[2].default_value = 0.5
    res = _math(g, 'ADD', inp["Viewport Res"], _math(g, 'MULTIPLY', is_render.outputs[0],
                _math(g, 'SUBTRACT', inp["Render Res"], inp["Viewport Res"])))
    down = _math(g, 'MINIMUM', _math(g, 'DIVIDE', res, width), 1.0)
    up = _math(g, 'DIVIDE', 1.0, down)

    # ---- low resolution: everything below works on down-scaled buffers, radii in their pixels
    img = scale(inp["Image"], down)
    signed_lo = _math(g, 'MULTIPLY', channel(scale(signed, down)), down)
    far = _math(g, 'MULTIPLY', _math(g, 'MAXIMUM', signed_lo, 0.0), inp["Kernel Scale"])
    # Pixels in focus must not smear into the blur behind them: blur only the part of the image that is
    # behind the focus plane, then divide by the same mask blurred with the same radius.
    behind = _math(g, 'MINIMUM', _math(g, 'MAXIMUM', signed_lo, 0.0), 1.0)

    if zones:
        # The cat's eye turns with the direction from the image centre and grows with the distance from it,
        # so the frame is split into a centre and RINGS x ZONES sectors. Each is blurred with its own kernel
        # and weighted by where the light comes from; neighbouring kernels cross-fade.
        co = g.nodes.new("CompositorNodeImageCoordinates")
        g.links.new(img, co.inputs["Image"])
        xy = g.nodes.new("ShaderNodeSeparateXYZ")
        g.links.new(co.outputs["Uniform"], xy.inputs[0])
        ln = g.nodes.new("ShaderNodeVectorMath")
        ln.operation = 'LENGTH'
        g.links.new(co.outputs["Uniform"], ln.inputs[0])
        height = _math(g, 'MINIMUM', _math(g, 'DIVIDE', ln.outputs["Value"], FF_CORNER / 18.0), 1.0)
        angle = _math(g, 'ARCTAN2', xy.outputs[1], xy.outputs[0])
        stops = (0.0,) + RINGS
        total = None
        for name, ring, direction in zone_kernels():
            idx = 0 if ring is None else ring + 1
            # Tent function over image height, peaking at this ring and reaching zero at its neighbours.
            w = None
            if idx > 0:
                w = _math(g, 'DIVIDE', _math(g, 'SUBTRACT', height, stops[idx - 1]), stops[idx] - stops[idx - 1])
            if idx < len(stops) - 1:
                fall = _math(g, 'DIVIDE', _math(g, 'SUBTRACT', stops[idx + 1], height), stops[idx + 1] - stops[idx])
                w = fall if w is None else _math(g, 'MINIMUM', w, fall)
            w = _math(g, 'MINIMUM', _math(g, 'MAXIMUM', w, 0.0), 1.0)
            if ring is not None:
                # Angular tent with period pi: |cos| folds opposite directions together.
                d = _math(g, 'ARCCOSINE', _math(g, 'ABSOLUTE', _math(g, 'COSINE',
                          _math(g, 'SUBTRACT', angle, direction * math.pi / ZONES))))
                w = _math(g, 'MULTIPLY', w, _math(g, 'MAXIMUM', _math(g, 'SUBTRACT', 1.0, _math(g, 'MULTIPLY', d, ZONES / math.pi)), 0.0))
            part = blur(_multiply(g, img, _math(g, 'MULTIPLY', w, behind)), image_node(name), far)
            total = part if total is None else mix(1.0, total, part, 'ADD')
    else:
        total = blur(_multiply(g, img, behind), image_node("K_Far"), far)
    weight = _math(g, 'MAXIMUM', channel(blur(behind, image_node("K_Mask"), far)), 1e-4)
    far_img = mix(1.0, total, weight, 'DIVIDE')
    composed = mix(behind, img, far_img)

    # Objects in front of the focus plane spill over what is behind them, so they are blurred as a separate
    # layer with coverage. A gather blur only reaches as far as each pixel's own radius, so the radius used
    # is the largest near-field radius within reach (a dilation): pixels just outside a foreground silhouette
    # then collect its light, and the silhouette dissolves instead of staying cut out.
    near = _math(g, 'MAXIMUM', _math(g, 'MULTIPLY', signed_lo, -1.0), 0.0)
    cap_lo = _math(g, 'MULTIPLY', cap, down)
    dil = g.nodes.new("CompositorNodeDilateErode")
    dil.inputs["Type"].default_value = "Distance"
    g.links.new(near, dil.inputs["Mask"])
    g.links.new(_math(g, 'CEIL', cap_lo), dil.inputs["Size"])
    soft = g.nodes.new("CompositorNodeBlur")
    size = g.nodes.new("ShaderNodeCombineXYZ")
    half_cap = _math(g, 'MULTIPLY', cap_lo, 0.5)
    g.links.new(half_cap, size.inputs[0])
    g.links.new(half_cap, size.inputs[1])
    g.links.new(dil.outputs[0], soft.inputs["Image"])
    g.links.new(size.outputs[0], soft.inputs["Size"])
    reach = _math(g, 'MAXIMUM', near, channel(soft.outputs[0]))
    radius = _math(g, 'MULTIPLY', reach, inp["Kernel Scale"])
    layer = _math(g, 'MINIMUM', _math(g, 'MAXIMUM', _math(g, 'SUBTRACT', near, 0.5), 0.0), 1.0)
    near_rgb = blur(_multiply(g, composed, layer), image_node("K_Near"), radius)
    coverage = channel(blur(layer, image_node("K_NearMask"), radius))
    near_img = mix(1.0, near_rgb, _math(g, 'MAXIMUM', coverage, 1e-3), 'DIVIDE')
    # What lies behind a foreground object was never rendered, so over the object itself the blurred layer
    # has to be opaque; elsewhere coverage is doubled, as in most real-time near-field blurs, so thin objects
    # do not turn into faint ghosts.
    coverage = _math(g, 'MAXIMUM', _math(g, 'MINIMUM', _math(g, 'MULTIPLY', coverage, 2.0), 1.0), layer)

    # ---- back to full resolution: sharp where the blur is under a couple of pixels
    out = mix(ramp(_math(g, 'MAXIMUM', signed, 0.0)), inp["Image"], scale(far_img, up))
    weight = _math(g, 'MULTIPLY', coverage, ramp(_math(g, 'MULTIPLY', reach, up)))
    out = mix(channel(scale(weight, up)), out, scale(near_img, up))
    g.links.new(out, go.inputs["Image"])
    g["postfx_zones"] = zones


def _bokeh():
    g, _, _ = _new_group("PostFX Bokeh", [("Depth", 1.0, 0.0, 1e10), ("Focus", 10.0, 0.0, 1e6), ("Focal", 50.0, 1.0, 5000.0),
                                          ("F-Stop", 2.8, 0.1, 128.0), ("Sensor", 36.0, 1.0, 200.0),
                                          ("Max Radius", 0.05, 0.0, 0.5), ("Kernel Scale", 1.0, 0.0, 10.0),
                                          ("Render Width", 1920.0, 1.0, 1e5), ("Render Res", 960.0, 64.0, 1e5),
                                          ("Viewport Res", 480.0, 64.0, 1e5)])
    _rebuild_bokeh(g, False)
    return g


def _camera(scene):
    """The scene camera's data, or None when the scene has no camera object."""
    c = scene.camera
    return c.data if c and c.type == 'CAMERA' else None


def focus_depth(cam_obj):
    cam = cam_obj.data
    if cam.dof.focus_object:
        return abs((cam_obj.matrix_world.inverted() @ cam.dof.focus_object.matrix_world.translation).z)
    return cam.dof.focus_distance


def sync(scene):
    """Push the camera state into the optical depth of field and refresh the kernels when the optics change."""
    t = _tree(scene)
    if not t or not scene.postfx_enabled or t.get("postfx_version") != VERSION:
        return
    node, star_node = t.nodes.get("PF_Bokeh"), t.nodes.get("PF_Star")
    star = star_node.node_tree.nodes.get("K_Star") if star_node else None
    cam = _camera(scene)
    if node is None or cam is None:
        return
    op = scene.postfx_optics
    optical = scene.postfx_dof == 'OPTICAL'
    if node.mute == optical:
        node.mute = not optical
    if optical and cam.dof.use_dof:
        cam.dof.use_dof = False
    spec = LENSES.get(scene.postfx_lens)
    fstop = max(cam.dof.aperture_fstop, 0.1)
    stop = min(1.0, (spec["fmax"] if spec else op.max_aperture) / fstop)
    o = {k: getattr(op, k) for k in OPTICS_KEYS}
    star_size = max(17, int(STAR_RES * op.star_size) | 1)
    r = scene.render
    render_width = max(r.resolution_x, r.resolution_y) * r.resolution_percentage // 100
    ratio = cam.dof.aperture_ratio
    for key, value in (("Focus", focus_depth(scene.camera)), ("Focal", cam.lens), ("F-Stop", fstop),
                       ("Sensor", cam.sensor_width), ("Max Radius", op.max_blur), ("Kernel Scale", _kernel_half(o, stop)),
                       ("Render Width", render_width), ("Render Res", op.render_res), ("Viewport Res", op.viewport_res)):
        if abs(node.inputs[key].default_value - value) > 1e-6:
            node.inputs[key].default_value = value
    zones = optical and o["cat"] > 0.0
    an = scene.postfx_anamorphic
    a = {k: (tuple(getattr(an, k)) if k in ("core", "tip") else getattr(an, k)) for k in ANAMORPHIC_KEYS}
    sig = repr((sorted(o.items()), sorted(a.items()), round(stop, 4), round(ratio, 3), star_size, zones, optical))
    g = node.node_tree
    if t.get("postfx_sig") == sig and g.get("postfx_zones") == zones:
        return
    if g.get("postfx_zones") != zones:
        _rebuild_bokeh(g, zones)
    if optical:
        kernels = {"K_Far": bokeh_kernel(o, stop, 1.0, None, ratio), "K_Near": bokeh_kernel(o, stop, -1.0, None, ratio)}
        kernels["K_Mask"] = kernels["K_Far"]
        kernels["K_NearMask"] = kernels["K_Near"]
        if zones:
            for name, ring, direction in zone_kernels()[1:]:
                kernels[name] = bokeh_kernel(o, stop, 1.0, direction * math.pi / ZONES, ratio, RINGS[ring])
        for name, arr in kernels.items():
            g.nodes[name].image = _image("PostFX " + name, arr)
    if star is not None:
        star.image = _image("PostFX K_Star", star_kernel(star_size, o, stop))
    streak_node = t.nodes.get("PF_Streak")
    streak = streak_node.node_tree.nodes.get("K_Streak") if streak_node else None
    if streak is not None:
        streak.image = _image("PostFX K_Streak", streak_kernel(a))
        _sock(streak_node, "Tint").default_value = (*a["core"], 1.0)
    t["postfx_sig"] = sig


# Sub-group name -> function that creates it. CHAIN refers to these by name.
BUILDERS = {"PostFX Bokeh": _bokeh, "PostFX Star": _star, "PostFX Streak": _streak, "PostFX Squeeze": _squeeze,
            "PostFX Vignette": _vignette, "PostFX Veil": _veil, "PostFX Tone": _tone, "PostFX Grain": _grain}


# ---------------------------------------------------------------- chain

def _tree(scene):
    t = scene.compositing_node_group
    if t and t.name.startswith(GROUP):
        return t
    t = scene.postfx_tree  # switched off: the chain is kept but detached from the scene
    return t if t and not scene.postfx_enabled else None


def _remove(scene):
    t = _tree(scene)
    if t:
        if scene.compositing_node_group == t:
            scene.compositing_node_group = None
        scene.postfx_tree = None
        bpy.data.node_groups.remove(t)
    for name in BUILDERS:
        g = bpy.data.node_groups.get(name)
        if g and g.users == 0:
            bpy.data.node_groups.remove(g)
    for img in [i for i in bpy.data.images if i.name.startswith("PostFX K_") and i.users == 0]:
        bpy.data.images.remove(img)


def _build(scene):
    t = bpy.data.node_groups.new(GROUP, "CompositorNodeTree")
    t["postfx_version"] = VERSION
    t.interface.new_socket("Image", in_out='OUTPUT', socket_type='NodeSocketColor')
    for layer in scene.view_layers:
        layer.use_pass_z = True  # the optical depth of field reads the Depth pass
    labels = {name: title for name, title, _ in PANEL}
    src = t.nodes.new("CompositorNodeRLayers")
    src.location = (-260, 0)
    prev = src.outputs["Image"]
    for i, (name, kind, fixed) in enumerate(CHAIN):
        if kind in BUILDERS:
            n = t.nodes.new("CompositorNodeGroup")
            n.node_tree = bpy.data.node_groups.get(kind) or BUILDERS[kind]()
        else:
            n = t.nodes.new(kind)
        n.name = name
        n.label = labels.get(name, name[3:])
        n.location = (i * 220, 0)
        _set(n, fixed)
        if name == "PF_Bokeh":
            n.mute = True
            t.links.new(src.outputs["Depth"], n.inputs["Depth"])

        t.links.new(prev, n.inputs["Image"])
        prev = n.outputs["Image"]
    out = t.nodes.new("NodeGroupOutput")
    out.location = (len(CHAIN) * 220, 0)
    t.links.new(prev, out.inputs["Image"])
    scene.compositing_node_group = t
    scene.postfx_tree = t
    if not scene.postfx_enabled:
        scene.postfx_enabled = True
    return t


def apply_preset(scene, preset):
    t = _tree(scene)
    if not t:
        return
    values = PRESETS[preset]
    for name, neutral in NEUTRAL.items():
        n = t.nodes.get(name)
        if n is None:
            continue
        _set(n, neutral)
        _set(n, values.get(name, {}))
        n.mute = name not in values


_busy = False  # True while the add-on itself sets properties; the update callbacks then do nothing


@contextmanager
def _quiet():
    global _busy
    prev, _busy = _busy, True
    try:
        yield
    finally:
        _busy = prev


def apply_lens(scene):
    """Mount the selected lens: its optics replace the look's, and the camera takes its focal length and iris."""
    t, spec = _tree(scene), LENSES.get(scene.postfx_lens)
    if not t or not spec:
        return
    fstop = max(scene.postfx_fstop, spec["fmax"])
    if fstop != scene.postfx_fstop:
        with _quiet():
            scene.postfx_fstop = fstop
    res = scene.render
    aspect = min(res.resolution_x, res.resolution_y) / max(res.resolution_x, res.resolution_y)
    values = lens_values(spec, fstop, aspect)
    for name in LENS_NODES:
        n = t.nodes.get(name)
        if n is None:
            continue
        _set(n, NEUTRAL[name])
        _set(n, values.get(name, {}))
        n.mute = name not in values
    cam = _camera(scene)
    with _quiet():
        op, lo = scene.postfx_optics, LENS_OPTICS.get(scene.postfx_lens, {})
        op.blades, op.curvature = spec["blades"], (0.8 if spec["rounded"] else 0.0)
        op.sa, op.loca, op.cat, op.rings = lo.get("sa", 0.0), lo.get("loca", 0.0), lo.get("cat", 0.0), lo.get("rings", 0.0)
        if scene.postfx_dof == 'OFF':
            scene.postfx_dof = 'OPTICAL'
        if cam:
            cam.lens, cam.sensor_width = spec["focal"], 36.0
            cam.dof.use_dof = scene.postfx_dof == 'EEVEE'
            cam.dof.aperture_fstop = fstop
            # An iris is round wide open; straight blades show once it is stopped down.
            cam.dof.aperture_blades = 0 if spec["rounded"] or fstop < spec["fmax"] * 1.12 else spec["blades"]
            cam.dof.aperture_ratio = spec.get("ratio", 1.0)
        if spec.get("streaks"):
            scene.postfx_anamorphic.core = spec["streaks"][1][:3]
    sync(scene)


def apply_all(scene):
    apply_preset(scene, scene.postfx_preset)
    apply_lens(scene)
    sync(scene)


# ---------------------------------------------------------------- UI

def sharp_range(cam_obj):
    """Near and far limits (metres) of acceptable sharpness; far is None when it reaches infinity."""
    cam, s = cam_obj.data, focus_depth(cam_obj)
    f = cam.lens / 1000.0
    coc = cam.sensor_width / 1000.0 / 1200.0
    h = f * f / (max(cam.dof.aperture_fstop, 1e-4) * coc) + f
    return h * s / (h + s), (h * s / (h - s) if s < h else None)


def _snapshot(t):
    """Mute state and unlinked input values of every effect node, keyed by node name and socket identifier."""
    if t is None:
        return None
    snap = {}
    for n in t.nodes:
        if not n.name.startswith("PF_"):
            continue
        values = {}
        for sock in n.inputs:
            if not sock.is_linked and hasattr(sock, "default_value"):
                v = sock.default_value
                values[sock.identifier] = v if isinstance(v, (int, float, str, bool)) else tuple(v)
        snap[n.name] = (n.mute, values)
    return snap


def _restore(t, snap):
    for name, (mute, values) in snap.items():
        n = t.nodes.get(name)
        if n is None:
            continue
        n.mute = mute
        for sock in n.inputs:
            if sock.identifier in values and not sock.is_linked:
                try:
                    sock.default_value = values[sock.identifier]
                except (TypeError, ValueError):
                    pass  # the socket changed type between versions; keep the new default


class PF_OT_build(bpy.types.Operator):
    bl_idname = "postfx.build"
    bl_label = "Build Chain"
    bl_description = "Create the post effect chain as this scene's compositor"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sc = context.scene
        if sc.compositing_node_group and not _tree(sc):
            self.report({'ERROR'}, "Scene already has another compositor node group; not overwriting")
            return {'CANCELLED'}
        old = _snapshot(_tree(sc))
        _remove(sc)
        t = _build(sc)
        if old:
            # Rebuilding an existing chain (for example after an update) keeps every value that was set,
            # instead of reloading the look and the lens over the user's adjustments.
            _restore(t, old)
            sync(sc)
            return {'FINISHED'}
        cam = _camera(sc)
        if cam and sc.postfx_dof != 'OPTICAL':
            with _quiet():
                sc.postfx_dof = 'EEVEE' if cam.dof.use_dof else 'OFF'
        apply_all(sc)
        return {'FINISHED'}


class PF_OT_remove(bpy.types.Operator):
    bl_idname = "postfx.remove"
    bl_label = "Remove Chain"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        _remove(context.scene)
        return {'FINISHED'}


class PF_PT_panel(bpy.types.Panel):
    bl_label = "bflare"
    bl_idname = "PF_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "bflare"

    def draw_header(self, context):
        if _tree(context.scene):
            self.layout.prop(context.scene, "postfx_enabled", text="")

    def draw(self, context):
        lo, sc = self.layout, context.scene
        lo.use_property_split = True
        lo.use_property_decorate = False
        lo.active = sc.postfx_enabled
        t = _tree(sc)
        if not t:
            lo.operator("postfx.build", icon='NODE_COMPOSITING')
            return
        if t.get("postfx_version") != VERSION:
            lo.label(text="Chain is from an older version")
            lo.operator("postfx.build", text="Rebuild Chain")
            return

        lo.prop(sc, "postfx_preset", text="Look")
        lo.prop(sc, "postfx_lens", text="Lens")
        lo.prop(context.space_data.shading, "use_compositor", text="Viewport")

        for name, title, rows in PANEL:
            n = t.nodes.get(name)
            if n is None:
                continue
            header, body = lo.panel("postfx_" + name, default_closed=True)
            header.use_property_split = False
            header.prop(n, "mute", text=title, invert_checkbox=True)
            if body:
                body.active = not n.mute
                for key, label in rows:
                    s = _sock(n, key)
                    if s is not None:
                        body.prop(s, "default_value", text=label)
                if name == "PF_Star":
                    body.prop(sc.postfx_optics, "star_size")

        cam = _camera(sc)
        if cam:
            header, body = lo.panel("postfx_dof", default_closed=True)
            header.label(text="Depth of Field")
            if body:
                body.prop(sc, "postfx_dof", text="Mode")
                optical = sc.postfx_dof == 'OPTICAL'
                op = sc.postfx_optics
                if context.space_data.region_3d.view_perspective != 'CAMERA':
                    # EEVEE only draws depth of field when looking through the camera.
                    body.operator("view3d.view_camera", text="Look Through Camera", icon='VIEW_CAMERA')
                    body.operator("view3d.camera_to_view", text="Move Camera to This View")
                else:
                    # Lets the user orbit and fly normally while staying in the camera, so the blur stays visible.
                    body.prop(context.space_data, "lock_camera", text="Navigate With Camera")
                col = body.column()
                col.active = sc.postfx_dof != 'OFF'
                col.prop(cam.dof, "focus_object", text="Focus On")
                row = col.row()
                row.active = cam.dof.focus_object is None
                row.prop(cam.dof, "focus_distance", text="Distance")
                mounted = sc.postfx_lens in LENSES
                if mounted:
                    col.prop(sc, "postfx_fstop", text="F-Stop")
                else:
                    col.prop(cam.dof, "aperture_fstop", text="F-Stop")
                row = col.row()
                row.enabled = not mounted
                row.prop(cam, "lens", text="Focal Length")
                near, far = sharp_range(sc.camera)
                far = "infinity" if far is None else "%.2f m" % far
                col.label(text="In focus: %.2f m to %s" % (near, far))
                if optical:
                    if not mounted:
                        col.prop(op, "max_aperture")
                    col.prop(op, "max_blur")
                    col.separator()
                    for key in OPTICS_KEYS:
                        col.prop(op, key)
                else:
                    sub = col.column()
                    sub.enabled = not mounted
                    sub.prop(cam.dof, "aperture_blades", text="Blades")
                    col.prop(sc.eevee, "use_bokeh_jittered", text="High Quality")

        streak, squeeze = t.nodes.get("PF_Streak"), t.nodes.get("PF_Squeeze")
        header, body = lo.panel("postfx_anamorphic", default_closed=True)
        header.label(text="Anamorphic")
        if body and streak and squeeze:
            an = sc.postfx_anamorphic
            if cam:
                body.prop(cam.dof, "aperture_ratio", text="Bokeh Squeeze")
            sub_h, sub = body.panel("postfx_anamorphic_streak", default_closed=False)
            sub_h.use_property_split = False
            sub_h.prop(streak, "mute", text="Flare Streak", invert_checkbox=True)
            if sub:
                sub.active = not streak.mute
                sub.prop(_sock(streak, "Strength"), "default_value", text="Strength")
                sub.prop(_sock(streak, "Threshold"), "default_value", text="Threshold")
                for key in ANAMORPHIC_KEYS:
                    row = sub.row()
                    row.active = key != "spacing" or an.lines > 1
                    row.prop(an, key)
            sub_h, sub = body.panel("postfx_anamorphic_distortion", default_closed=False)
            sub_h.use_property_split = False
            sub_h.prop(squeeze, "mute", text="Axis Distortion", invert_checkbox=True)
            if sub:
                sub.active = not squeeze.mute
                sub.prop(_sock(squeeze, "Horizontal"), "default_value", text="Horizontal %")
                sub.prop(_sock(squeeze, "Vertical"), "default_value", text="Vertical %")

        header, body = lo.panel("postfx_quality", default_closed=True)
        header.label(text="Quality")
        if body:
            col = body.column(heading="Blur Resolution")
            col.prop(sc.postfx_optics, "viewport_res")
            col.prop(sc.postfx_optics, "render_res")

        header, body = lo.panel("postfx_motion", default_closed=True)
        header.use_property_split = False
        header.prop(sc.render, "use_motion_blur", text="Motion Blur")
        if body:
            body.active = sc.render.use_motion_blur
            body.prop(sc.render, "motion_blur_shutter", text="Shutter")

        header, body = lo.panel("postfx_display", default_closed=True)
        header.label(text="Display")
        if body:
            body.prop(sc.view_settings, "view_transform", text="Transform")
            body.prop(sc.view_settings, "look", text="Look")

        lo.separator()
        lo.operator("postfx.remove")


def _optics_update(self, context):
    if not _busy:
        sync(context.scene)


class PF_Anamorphic(bpy.types.PropertyGroup):
    F, I, C = bpy.props.FloatProperty, bpy.props.IntProperty, bpy.props.FloatVectorProperty
    length: F(name="Length", description="Reach of the streak on each side, as a fraction of the image width",
              default=0.35, min=0.02, max=1.0, subtype='FACTOR', update=_optics_update)
    thickness: F(name="Thickness", description="Height of the streak as a fraction of the image width",
                 default=0.002, min=0.0005, max=0.03, precision=4, update=_optics_update)
    falloff: F(name="Falloff", description="How quickly the streak fades towards its tips: 1 is linear, higher is a "
                                           "bright core with faint tails",
               default=2.5, min=0.3, max=12.0, update=_optics_update)
    core: C(name="Core Colour", subtype='COLOR', size=3, default=(0.2, 0.45, 1.0), min=0.0, soft_max=1.0,
            update=_optics_update)
    tip: C(name="Tip Colour", description="Colour the streak shifts to towards its ends", subtype='COLOR', size=3,
           default=(0.45, 0.25, 1.0), min=0.0, soft_max=1.0, update=_optics_update)
    lines: I(name="Lines", description="Parallel streaks, as from several cylindrical elements",
             default=1, min=1, max=5, update=_optics_update)
    spacing: F(name="Line Spacing", description="Distance between parallel streaks, as a fraction of the image width",
               default=0.006, min=0.001, max=0.05, precision=4, update=_optics_update)
    del F, I, C


class PF_Optics(bpy.types.PropertyGroup):
    F, I = bpy.props.FloatProperty, bpy.props.IntProperty
    max_aperture: F(name="Max Aperture", description="Widest f-number of the lens; the iris is round at this setting",
                    default=1.4, min=0.5, max=32.0, precision=2, update=_optics_update)
    max_blur: F(name="Max Blur", description="Largest blur radius as a fraction of the image width",
                default=0.05, min=0.005, max=0.2, precision=3, update=_optics_update)
    blades: I(name="Blades", description="Iris blades; fewer than 3 gives a round iris",
              default=9, min=0, max=16, update=_optics_update)
    curvature: F(name="Blade Curvature", description="0 = straight blades, 1 = round opening at every f-stop",
                 default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=_optics_update)
    rotation: F(name="Blade Rotation", default=0.0, subtype='ANGLE', update=_optics_update)
    sa: F(name="Spherical Aberration",
          description="Above 0 (undercorrected): smooth discs behind the focus, outlined in front. "
                      "Below 0 (overcorrected): bright-edged soap bubbles behind the focus. Fades when stopped down",
          default=0.0, min=-0.3, max=1.0, update=_optics_update)
    loca: F(name="Axial Colour", description="Green outline behind the focus plane and magenta in front",
            default=0.0, min=0.0, max=0.3, subtype='FACTOR', update=_optics_update)
    cat: F(name="Mechanical Vignetting",
           description="Clips highlights into cat's eyes towards the frame edge (swirl). Disappears when stopped down. "
                       "Costs 8 extra blurs",
           default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=_optics_update)
    rings: F(name="Onion Rings", description="Concentric rings inside highlights, as left by moulded aspherical elements",
             default=0.0, min=0.0, max=1.0, subtype='FACTOR', update=_optics_update)
    ring_count: F(name="Ring Count", default=6.0, min=1.0, max=30.0, update=_optics_update)
    apodization: F(name="Apodization", description="Darkens the rim of the pupil for soft-edged highlights (STF lenses)",
                   default=0.0, min=0.0, max=6.0, update=_optics_update)
    obstruction: F(name="Central Obstruction", description="Blocks the middle of the pupil: mirror-lens doughnuts",
                   default=0.0, min=0.0, max=0.9, subtype='FACTOR', update=_optics_update)
    viewport_res: I(name="Viewport", description="Width of the buffer the depth of field is computed on in the "
                    "viewport. Lower is faster; the cost falls with the fourth power", default=480, min=128, max=4096,
                    update=_optics_update)
    render_res: I(name="Render", description="Width of the buffer the depth of field is computed on in the final "
                  "render. Raise it for cleaner edges near the focus plane", default=960, min=128, max=8192,
                  update=_optics_update)
    star_size: F(name="Size", description="Reach of the diffraction pattern as a fraction of the image width",
                 default=0.12, min=0.02, max=0.5, subtype='FACTOR', update=_optics_update)
    del F, I


def _dof_update(self, context):
    if _busy:
        return
    cam = _camera(self)
    if cam:
        cam.dof.use_dof = self.postfx_dof == 'EEVEE'
    sync(self)


def _enabled_update(self, context):
    # Detaching the chain turns compositing off for the viewport and the render alike, and stops the handlers.
    t = self.postfx_tree or _tree(self)
    if t is None:
        return
    self.postfx_tree = t
    if self.postfx_enabled:
        self.compositing_node_group = t
        t["postfx_sig"] = ""
        sync(self)
    elif self.compositing_node_group == t:
        self.compositing_node_group = None


@persistent
def _on_change(scene, *args):
    """Keeps focus distance, f-stop and focal length in step with the camera, also during animation."""
    if _busy or scene is None or not hasattr(scene, "postfx_dof"):
        return
    with _quiet():
        sync(scene)


@persistent
def _on_load(*args):
    # Generated kernel images are not saved with the file; force them to be rebuilt.
    for g in bpy.data.node_groups:
        if g.name.startswith(GROUP) and "postfx_sig" in g:
            g["postfx_sig"] = ""


classes = (PF_Anamorphic, PF_Optics, PF_OT_build, PF_OT_remove, PF_PT_panel)


def _preset_update(self, context):
    apply_all(self)


def _lens_update(self, context):
    spec = LENSES.get(self.postfx_lens)
    if spec:
        with _quiet():
            self.postfx_fstop = spec["fmax"]
    apply_all(self)


def _fstop_update(self, context):
    if not _busy:
        apply_lens(self)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    S = bpy.types.Scene
    S.postfx_preset = bpy.props.EnumProperty(
        name="Look", items=[(k, k, "") for k in PRESETS], default="Cinematic", update=_preset_update)
    S.postfx_lens = bpy.props.EnumProperty(
        name="Lens", description="Mount a lens profile on the scene camera",
        items=[("NONE", "None", "Use the look's own lens settings")]
        + [(k, v["name"], v["note"]) for k, v in LENSES.items()], update=_lens_update)
    S.postfx_fstop = bpy.props.FloatProperty(
        name="F-Stop", description="Aperture of the mounted lens; cannot open wider than its maximum",
        default=2.8, min=0.7, soft_max=22.0, max=64.0, precision=2, update=_fstop_update)
    S.postfx_enabled = bpy.props.BoolProperty(
        name="bflare", description="Run the post effect chain in the viewport and the render. Turn off to work in a "
        "heavy scene; every setting is kept", default=True, update=_enabled_update)
    S.postfx_tree = bpy.props.PointerProperty(type=bpy.types.NodeTree, options={'HIDDEN'})
    S.postfx_optics = bpy.props.PointerProperty(type=PF_Optics)
    S.postfx_anamorphic = bpy.props.PointerProperty(type=PF_Anamorphic)
    S.postfx_dof = bpy.props.EnumProperty(
        name="Depth of Field", update=_dof_update, default='OFF',
        items=[('OFF', "Off", ""),
               ('EEVEE', "EEVEE", "The renderer's own depth of field: fast, plain discs, camera view only"),
               ('OPTICAL', "Optical", "Blur computed from the lens pupil: aberrations, iris shape, cat's eye")])
    bpy.app.handlers.depsgraph_update_post.append(_on_change)
    bpy.app.handlers.frame_change_post.append(_on_change)
    bpy.app.handlers.load_post.append(_on_load)


def unregister():
    for handlers, fn in ((bpy.app.handlers.depsgraph_update_post, _on_change),
                         (bpy.app.handlers.frame_change_post, _on_change), (bpy.app.handlers.load_post, _on_load)):
        if fn in handlers:
            handlers.remove(fn)
    S = bpy.types.Scene
    del S.postfx_preset, S.postfx_lens, S.postfx_fstop, S.postfx_optics, S.postfx_anamorphic, S.postfx_dof
    del S.postfx_enabled, S.postfx_tree
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
