"""One-shot generator for cictikz symbol YAMLs.

Coordinates are figure units (TikZ cm, \\grid = 1.6), relative to the
macro entry point, y up, read out of the macro bodies in ckt_lib.tex.
"""

import textwrap
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src/cictikz/data/symbols"

HEAD = """\
# cictikz symbol metadata. Coordinates are figure units (\\grid = 1.6),
# relative to the macro entry point, y up, taken from the macro body in
# cictikz_lib.tex. Transistor gate pins are at the END of the gate lead
# (the circuitikz .gate anchor, measured); in TikZ prefer the node
# anchor (e.g. M1.gate) over the raw coordinate.
"""

# End of the circuitikz gate lead, measured from the .gate anchor in the
# TeX log (-27.88345pt / 28.4528pt-per-unit = 0.98); same for nmos/pmos.
GATE_X = 0.98

def mos(name, macro, nargs, kind, mirror, labeled):
    gx = GATE_X if mirror else -GATE_X
    arg_doc = ["instance name (becomes circuitikz node, e.g. M1)"]
    if labeled:
        arg_doc.append("gate port label, e.g. $v_i$ (empty {} suppresses the port)")
    ex = (f"\\draw (0,0) \\vground \\{name}{{M1}}"
          + ("{$v_i$}" if labeled else "") + ";")
    # Drawn upward, an nmos enters at the source, a pmos at the drain
    # (measured from the circuitikz anchors).
    top, bot = ("drain", "source") if kind == "nmos" else ("source", "drain")
    # xschem pin offsets measured from the installed .sym files; nfet has
    # D up (y = -30), pfet has S up. Wrapper aliases carry their own maps.
    if kind == "nmos":
        pin_xy = {"drain": [20, -30], "gate": [-20, 0], "source": [20, 30]}
        sym = "sky130_fd_pr/nfet_01v8.sym"
        aliases = {
            "JNW_TR_SKY130A/JNWTR_NCHDL.sym":
                {"pin_xy": {"drain": [40, -30], "gate": [0, 0], "source": [40, 30]}},
            "SUN_TR_SKY130NM/SUNTR_NCHDL.sym":
                {"pin_xy": {"drain": [40, -30], "gate": [0, 0], "source": [40, 30]}},
        }
    else:
        pin_xy = {"source": [20, -30], "gate": [-20, 0], "drain": [20, 30]}
        sym = "sky130_fd_pr/pfet_01v8.sym"
        aliases = {
            "JNW_TR_SKY130A/JNWTR_PCHDL.sym":
                {"pin_xy": {"source": [40, -30], "gate": [0, 0], "drain": [40, 30]}},
            "SUN_TR_SKY130NM/SUNTR_PCHDL.sym":
                {"pin_xy": {"source": [40, -30], "gate": [0, 0], "drain": [40, 30]}},
        }
    partner = {"vnmos": "vmnmos", "vmnmos": "vnmos", "vpmos": "vmpmos",
               "vmpmos": "vpmos", "lvnmos": "lvmnmos", "lvmnmos": "lvnmos",
               "lvpmos": "lvmpmos", "lvmpmos": "lvpmos"}[name]
    return {
        "name": name, "macro": "\\" + name, "nargs": nargs,
        "arg_doc": arg_doc,
        "description": f"{kind.upper()} transistor, vertical, {top} up"
                       + (", gate on the right (mirrored)" if mirror else ", gate on the left")
                       + (", with optional gate input port" if labeled else "")
                       + "; gate pin is the end of the gate lead",
        "entry": [0, 0], "exit": [0, 1.6],
        "height_grid": 1.6, "width_grid": 1.1,
        "pins": [
            {"name": top, "grid_xy": [0, 1.6], "direction": "inout"},
            {"name": "gate", "grid_xy": [gx, 0.8], "direction": "in"},
            {"name": bot, "grid_xy": [0, 0], "direction": "inout"},
        ],
        "nodes": ["<inst>.drain", "<inst>.gate", "<inst>.source", "<inst>.bulk"],
        "exports": ({"cicmos": [0, 1.6]} if labeled else {}),
        "arg_ports": ({"2": "gate"} if labeled else {}),
        "mirror": partner,
        "xschem": {
            "sym": sym, "origin": [0, 0.8], "pin_xy": pin_xy,
            "flip": 1 if mirror else 0,
            "params": "L=0.15 W=1 nf=1 m=1",
            "aliases": aliases,
        },
        "example": ex,
    }

END_COORD = {"resistor": "resEnd", "capacitor": "capEnd", "impedance": "impEnd"}


def twoterm(name, orient, desc, span=1.6, label=True, pinnames=("minus", "plus")):
    horiz = orient == "h"
    end = [span, 0] if horiz else [0, span]
    end_name = next(v for k, v in END_COORD.items() if k in name)
    d = {
        "exports": {"cStart": [0, 0], end_name: end},
        "name": name, "macro": "\\" + name, "nargs": 1 if label else 0,
        "arg_doc": ["value label, e.g. $R_s$"] if label else [],
        "description": desc,
        "entry": [0, 0], "exit": end,
        "height_grid": 0 if horiz else span, "width_grid": span if horiz else 0,
        "pins": [
            {"name": pinnames[0], "grid_xy": [0, 0], "direction": "inout"},
            {"name": pinnames[1], "grid_xy": end, "direction": "inout"},
        ],
        "example": ("\\draw (0,0) \\%s{%s};" % (name, "$Z$")) if label
                   else "\\draw (0,0) \\%s;" % name,
    }
    # Verified mappings: devices/res.sym has P up / M down at (0,-30)/(0,30),
    # capa.sym p/m likewise; the horizontal variants use xschem rot=1
    # (each rot step maps a pin (x,y) -> (-y,x), netlist-verified).
    if "resistor" in name:
        d["xschem"] = {
            "sym": "devices/res.sym", "origin": [0.8, 0] if horiz else [0, 0.8],
            "pin_xy": {"plus": [0, -30], "minus": [0, 30]},
            "rot": 1 if horiz else 0, "params": "value=1k",
            "aliases": {
                "sky130_fd_pr/res_high_po.sym": {},
                "JNW_TR_SKY130A/JNWTR_RPPO16.sym":
                    {"rot": 0, "origin": [0, 0],
                     "pin_xy": {"minus": [0, 0], "plus": [80, 0]}}
                    if horiz else None,
            },
        }
        if not horiz:
            del d["xschem"]["aliases"]["JNW_TR_SKY130A/JNWTR_RPPO16.sym"]
        else:
            d["xschem"]["aliases"]["JNW_TR_SKY130A/JNWTR_RPPO16.sym"] = \
                {"rot": 0, "origin": [0, 0],
                 "pin_xy": {"minus": [0, 0], "plus": [80, 0]}}
    elif "capacitor" in name:
        d["xschem"] = {
            "sym": "devices/capa.sym", "origin": [0.8, 0] if horiz else [0, 0.8],
            "pin_xy": {"plus": [0, -30], "minus": [0, 30]},
            "rot": 1 if horiz else 0, "params": "value=1p",
        }
        if not horiz:
            d["xschem"]["aliases"] = {
                "JNW_TR_SKY130A/JNWTR_CAPX1.sym":
                    {"pin_xy": {"plus": [0, -60], "minus": [0, 10]}},
            }
    return d

SYMS = []

for n, m in [("vnmos", False), ("vmnmos", True)]:
    SYMS.append(mos(n, n, 1, "nmos", m, False))
for n, m in [("vpmos", False), ("vmpmos", True)]:
    SYMS.append(mos(n, n, 1, "pmos", m, False))
for n, m in [("lvnmos", False), ("lvmnmos", True)]:
    SYMS.append(mos(n, n, 2, "nmos", m, True))
for n, m in [("lvpmos", False), ("lvmpmos", True)]:
    SYMS.append(mos(n, n, 2, "pmos", m, True))

SYMS += [
    twoterm("vresistor", "v", "Resistor, vertical (hand-rolled zig-zag, weight-matched to wires)"),
    twoterm("hresistor", "h", "Resistor, horizontal (hand-rolled zig-zag)"),
    twoterm("vcapacitor", "v", "Capacitor, vertical"),
    twoterm("hcapacitor", "h", "Capacitor, horizontal"),
    twoterm("vimpedance", "v", "Generic impedance box, vertical"),
    twoterm("himpedance", "h", "Generic impedance box, horizontal"),
]

SYMS += [
    {
        "name": "vground", "macro": "\\vground", "nargs": 0, "arg_doc": [],
        "exports": {"cStart": [0, 0]},
        "xschem": {"sym": "devices/gnd.sym", "origin": [0, 0],
                   "pin_xy": {"term": [0, 0]}, "params": "lab=GND", "net": "GND"},
        "description": "Ground symbol (three shrinking bars, downward). Path returns to entry.",
        "entry": [0, 0], "exit": [0, 0],
        "height_grid": 0.2, "width_grid": 0.4,
        "pins": [{"name": "term", "grid_xy": [0, 0], "direction": "supply"}],
        "example": "\\draw (0,0) \\vground \\vresistor{$R$};",
    },
    {
        "name": "vsupply", "macro": "\\vsupply", "nargs": 0, "arg_doc": [],
        "exports": {"vSupplyStart": [0, 0]},
        "xschem": {"sym": "devices/vdd.sym", "origin": [0, 0],
                   "pin_xy": {"term": [0, 0]}, "params": "lab=VDD", "net": "VDD"},
        "description": "Supply symbol (upward stub with slash). Path returns to entry.",
        "entry": [0, 0], "exit": [0, 0],
        "height_grid": 0.4, "width_grid": 0.4,
        "pins": [{"name": "term", "grid_xy": [0, 0], "direction": "supply"}],
        "example": "\\draw (M3.drain) \\vsupply;",
    },
    {
        "name": "vvsource", "macro": "\\vvsource", "nargs": 1,
        "xschem": {"sym": "devices/vsource.sym", "origin": [0, -1.2],
                   "pin_xy": {"plus": [0, -30], "minus": [0, 30]},
                   "params": "value=1.8"},
        "arg_doc": ["source label, e.g. $V_{DD}$"],
        "description": "Voltage source, vertical, drawn DOWNWARD 1.5 grid from entry",
        "entry": [0, 0], "exit": [0, -2.4],
        "height_grid": 2.4, "width_grid": 0.6,
        "pins": [
            {"name": "plus", "grid_xy": [0, 0], "direction": "inout"},
            {"name": "minus", "grid_xy": [0, -2.4], "direction": "inout"},
        ],
        "example": "\\draw (0,0) \\vvsource{$V_{DD}$} \\vground;",
    },
    {
        "name": "portIn", "macro": "\\portIn", "nargs": 1,
        "arg_doc": ["port label, e.g. $v_i$"],
        "description": "Input port: open circle at the current point, label to the left (anchor east)",
        "entry": [0, 0], "exit": [0, 0],
        "height_grid": 0, "width_grid": 0.3,
        "pins": [{"name": "term", "grid_xy": [0, 0], "direction": "in"}],
        "xschem": {"sym": "devices/ipin.sym", "pin_map": {"term": "p"}, "scale": 40},
        "example": "\\draw (M1.gate) \\portIn{$v_i$};",
    },
    {
        "name": "portmIn", "macro": "\\portmIn", "nargs": 1,
        "arg_doc": ["port label"],
        "description": "Input port, mirrored: label to the right (anchor west), for mirrored devices",
        "entry": [0, 0], "exit": [0, 0],
        "height_grid": 0, "width_grid": 0.3,
        "pins": [{"name": "term", "grid_xy": [0, 0], "direction": "in"}],
        "xschem": {"sym": "devices/ipin.sym", "pin_map": {"term": "p"}, "scale": 40},
        "example": "\\draw (M2.gate) \\portmIn{$v_b$};",
    },
    {
        "name": "portOut", "macro": "\\portOut", "nargs": 1,
        "arg_doc": ["port label, e.g. $v_o$"],
        "description": "Output port: junction dot at entry, 0.5 wire right, open circle, label right",
        "entry": [0, 0], "exit": [0.5, 0],
        "height_grid": 0, "width_grid": 0.8,
        "pins": [{"name": "term", "grid_xy": [0, 0], "direction": "out"}],
        "xschem": {"sym": "devices/opin.sym", "pin_map": {"term": "p"}, "scale": 40},
        "example": "\\draw (M1.drain) \\portOut{$v_o$};",
    },
    {
        "name": "hinv", "macro": "\\hinv", "nargs": 1,
        "arg_doc": ["instance name (becomes the not-port node, e.g. X1)"],
        "description": "Inverter (not port), horizontal, input left output right",
        "entry": [0, 0], "exit": [1.4, 0],
        "height_grid": 0.6, "width_grid": 1.4,
        "pins": [
            {"name": "in", "grid_xy": [0, 0], "direction": "in"},
            {"name": "out", "grid_xy": [1.4, 0], "direction": "out"},
        ],
        "nodes": ["<inst>.in 1", "<inst>.out"],
        "example": "\\draw (0,0) \\hinv{X1};",
    },
    {
        "name": "cicOta", "macro": "\\cicOta", "nargs": 0, "arg_doc": [],
        "exports": {"cicOta_inp": [0, 0], "cicOta_inn": [0, -1.6],
                    "cicOta_outp": [2.6, -1.6], "cicOta_outn": [2.6, 0]},
        "description": "Fully differential OTA outline (triangle, +/- in, -/+ out). "
                       "Exports coordinates cicOta_inp/inn/outp/outn; path returns to inp.",
        "entry": [0, 0], "exit": [0, 0],
        "height_grid": 2.4, "width_grid": 2.6,
        "pins": [
            {"name": "inp", "grid_xy": [0, 0], "direction": "in"},
            {"name": "inn", "grid_xy": [0, -1.6], "direction": "in"},
            {"name": "outp", "grid_xy": [2.6, -1.6], "direction": "out"},
            {"name": "outn", "grid_xy": [2.6, 0], "direction": "out"},
        ],
        "nodes": ["cicOta_inp", "cicOta_inn", "cicOta_outp", "cicOta_outn"],
        "example": textwrap.dedent("""\
            \\draw (0,0) \\cicOta;
            \\draw (cicOta_inp) \\portIn{$v_{ip}$};
            \\draw (cicOta_outn) \\portOut{$v_{on}$};"""),
    },
    {
        "name": "cmStd", "macro": "\\cmStd", "nargs": 0, "arg_doc": [],
        "exports": {"cStart": [0, 0]},
        "description": "Standard NMOS current mirror (M1 diode-connected, M2 output), "
                       "grounds included, current arrows i_i/i_o. Path returns to entry.",
        "entry": [0, 0], "exit": [0, 0],
        "height_grid": 2.1, "width_grid": 2.0,
        "pins": [
            {"name": "in", "grid_xy": [0, 2.1], "direction": "in"},
            {"name": "out", "grid_xy": [2.0, 2.1], "direction": "out"},
        ],
        "nodes": ["mn1.gate", "mn1.drain", "mn2.gate", "mn2.drain"],
        "example": "\\draw (0,0) \\cmStd;",
    },
    {
        "name": "cmCascode", "macro": "\\cmCascode", "nargs": 0, "arg_doc": [],
        "exports": {"cStart": [0, 0]},
        "description": "Cascoded NMOS current mirror (M1-M4, v_b bias port), grounds included. "
                       "Branches at x=0 and x=2.5, tops at y=3.7. Path returns to entry.",
        "entry": [0, 0], "exit": [0, 0],
        "height_grid": 3.7, "width_grid": 2.5,
        "pins": [
            {"name": "in", "grid_xy": [0, 3.7], "direction": "in"},
            {"name": "out", "grid_xy": [2.5, 3.7], "direction": "out"},
        ],
        "nodes": ["mn1.gate", "mn2.gate", "mn3.gate", "mn4.gate", "mn3.drain"],
        "example": "\\draw (0,0) \\cmCascode;",
    },
]

import yaml

OUT.mkdir(parents=True, exist_ok=True)
for s in SYMS:
    text = HEAD + yaml.safe_dump(s, sort_keys=False, allow_unicode=True, width=78)
    (OUT / f"{s['name']}.yaml").write_text(text)
    print("wrote", s["name"])
print(len(SYMS), "symbols")

# ---- reader-grade additions: the rest of the ckt_lib vocabulary ------
# Geometry traced from the macro bodies; pins are the usable terminals.

def block(name, nargs, desc, exit_, pins, exports=None, arg_doc=None, example=None):
    return {
        "name": name, "macro": "\\" + name, "nargs": nargs,
        "arg_doc": arg_doc or (["label"] * nargs),
        "description": desc, "entry": [0, 0], "exit": exit_,
        "height_grid": max((abs(p[1][1]) for p in []), default=0),
        "width_grid": 0,
        "pins": [{"name": n, "grid_xy": xy, "direction": d} for n, xy, d in pins],
        "exports": exports or {},
        "example": example or f"\\draw (0,0) \\{name}" + "{x}" * nargs + ";",
    }

MORE = [
    block("cicOtaSWP", 4, "Fully differential OTA outline with caller-set port labels (+in/-in/+out/-out)",
          [0, 0],
          [("inp", [0, 0], "in"), ("inn", [0, -1.6], "in"),
           ("outp", [2.6, -1.6], "out"), ("outn", [2.6, 0], "out")],
          exports={"cicOta_inp": [0, 0], "cicOta_inn": [0, -1.6],
                   "cicOta_outp": [2.6, -1.6], "cicOta_outn": [2.6, 0]},
          arg_doc=["+in label", "-in label", "+out label", "-out label"]),
    block("cicOtaSSWP", 2, "Single-ended OTA outline with caller-set input labels",
          [0, 0],
          [("inp", [0, 0], "in"), ("inn", [0, -0.8], "in"), ("out", [2.6, -0.4], "out")],
          exports={"cicOtaS_inp": [0, 0], "cicOtaS_inn": [0, -0.8],
                   "cicOtaS_out": [2.6, -0.4]},
          arg_doc=["+in label", "-in label"]),
    block("cmSfCascode", 0, "Cascode current mirror biased as source follower (M3/M4 under M1/M2)",
          [0, 0], [("in", [0, 3.7], "in"), ("out", [2, 3.7], "out")],
          exports={"cStart": [0, 0]}),
    block("cmSourceDeg", 0, "Source-degenerated current mirror (R_s under M1/M2), grounds included",
          [0, 0], [("in", [0, 3.7], "in"), ("out", [2, 3.7], "out")],
          exports={"cStart": [0, 0]}),
    block("cmRCascode", 0, "Cascode mirror with resistor-derived cascode bias",
          [0, 0], [("in", [0, 5.3], "in"), ("out", [2.5, 3.7], "out")],
          exports={"cmRStart": [0, 0], "cStart": [0, 3.2],
                   "resCon": [0, 4.8], "resEnd": [0, 4.8]}),
    block("filtLP", 2, "Passive RC low-pass: series R to shunt C",
          [1.6, 0], [("in", [0, 0], "in"), ("out", [1.6, 0], "out")],
          exports={"cStart": [1.6, -1.6], "resEnd": [1.6, 0], "capEnd": [1.6, 0]},
          arg_doc=["R label", "C label"]),
    block("filtHP", 2, "Passive RC high-pass: series C to shunt R",
          [1.6, 0], [("in", [0, 0], "in"), ("out", [1.6, 0], "out")],
          exports={"cStart": [1.6, -1.6], "capEnd": [1.6, 0], "resEnd": [1.6, 0]},
          arg_doc=["C label", "R label"]),
    block("filtActLP", 2, "Active RC low-pass: R into OTA virtual ground, C in feedback",
          [4.2, 0], [("in", [0, 0], "in"), ("out", [4.2, 0], "out")],
          exports={"cicStart": [0, 0], "resEnd": [1.6, 0], "capEnd": [3.7, 1],
                   "cStart": [1.6, -1.7],
                   "cicOta_inp": [1.6, 0], "cicOta_inn": [1.6, -1.6],
                   "cicOta_outp": [4.2, -1.6], "cicOta_outn": [4.2, 0]},
          arg_doc=["R label", "C label"]),
    block("filtActZ", 2, "Active filter with generic input/feedback impedances",
          [4.2, 0], [("in", [0, 0], "in"), ("out", [4.2, 0], "out")],
          exports={"cicStart": [0, 0], "impEnd": [3.7, 0.8], "cStart": [1.6, -1.7],
                   "cicOta_inp": [1.6, 0], "cicOta_inn": [1.6, -1.6],
                   "cicOta_outp": [4.2, -1.6], "cicOta_outn": [4.2, 0]},
          arg_doc=["input Z label", "feedback Z label"]),
    block("portDiffIn", 1, "Differential input port pair (+ over -, 1.6 apart)",
          [0, 0], [("plus", [0, 0], "in"), ("minus", [0, -1.6], "in")],
          exports={"cStart": [0, 0]}, arg_doc=["port label"]),
    block("portDiffOut", 1, "Differential output port pair (+ over -, 1.6 apart)",
          [0, 0], [("plus", [0.5, 0], "out"), ("minus", [0.5, -1.6], "out")],
          exports={"cStart": [0, 0]}, arg_doc=["port label"]),
    block("portOutDown", 1, "Output port drawn downward half a grid",
          [0, -0.8], [("term", [0, 0], "out")],
          exports={"cStart": [0, 0]}, arg_doc=["port label"]),
    block("curDown", 1, "Downward current arrow on a half-grid stub",
          [0, -0.8], [("term", [0, 0], "inout")], arg_doc=["current label"]),
    block("portCurDown", 1, "Downward current arrow with a label",
          [0, -0.8], [("term", [0, 0], "inout")], arg_doc=["current label"]),
    block("cicAdd", 0, "Summing node: circle with +",
          [0.4, 0], [("in", [0, 0], "in"), ("out", [0.4, 0], "out")]),
    block("cicH", 1, "Transfer-function box H(s)",
          [0.8, 0], [("in", [0, 0], "in"), ("out", [0.8, 0], "out")],
          arg_doc=["box label"]),
    block("trNmos", 0, "NMOS with labelled Gate/Drain/Source terminals (teaching figure)",
          [0, 0],
          [("drain", [0, 1.6], "inout"), ("gate", [-0.98, 0.8], "in"),
           ("source", [0, 0], "inout")],
          exports={"cStart": [0, 0]}),
    block("esdGgnmos", 0, "Grounded-gate NMOS ESD clamp with gate resistor",
          [0, 0], [("pin", [0.5, 3.2], "inout"), ("core", [-1, 3.2], "inout")],
          exports={"esdStart": [0, 0], "cStart": [-1, -1.6],
                   "esdRbot": [-1, -1.6], "top": [0, 3.2]}),
    block("anaQuestion", 0, "Current mirror bias question figure (M1-M3 with sources)",
          [0, 0], [], exports={"cStart": [0, 0]}),
    block("cicNand", 1, "NAND gate, hand-rolled house shape; exports <n>_in1/_in2/_out",
          [1.38, 0], [("in1", [0, 0.32], "in"), ("in2", [0, -0.32], "in"),
                      ("out", [1.38, 0], "out")],
          arg_doc=["instance name, e.g. g1"],
          example="\\draw (0,0) \\cicNand{g1};\n\\draw (-0.5,0.32) -- (g1_in1);"),
    block("cicAnd", 1, "AND gate, hand-rolled house shape",
          [1.18, 0], [("in1", [0, 0.32], "in"), ("in2", [0, -0.32], "in"),
                      ("out", [1.18, 0], "out")],
          arg_doc=["instance name"]),
    block("cicNor", 1, "NOR gate, hand-rolled house shape",
          [1.7, 0], [("in1", [0, 0.32], "in"), ("in2", [0, -0.32], "in"),
                     ("out", [1.7, 0], "out")],
          arg_doc=["instance name"]),
    block("cicOr", 1, "OR gate, hand-rolled house shape",
          [1.5, 0], [("in1", [0, 0.32], "in"), ("in2", [0, -0.32], "in"),
                     ("out", [1.5, 0], "out")],
          arg_doc=["instance name"]),
    block("cicInv", 1, "Inverter, hand-rolled house shape; exports <n>_in/_out",
          [1.1, 0], [("in", [0, 0], "in"), ("out", [1.1, 0], "out")],
          arg_doc=["instance name"]),
    block("cicBuf", 1, "Buffer (triangle, no bubble), hand-rolled house shape",
          [0.9, 0], [("in", [0, 0], "in"), ("out", [0.9, 0], "out")],
          arg_doc=["instance name"]),
    block("cicInvM", 1, "Inverter pointing left (for feedback paths); in right, out left",
          [-1.1, 0], [("in", [0, 0], "in"), ("out", [-1.1, 0], "out")],
          arg_doc=["instance name"]),
]

for s in MORE:
    text = HEAD + yaml.safe_dump(s, sort_keys=False, allow_unicode=True, width=78)
    (OUT / f"{s['name']}.yaml").write_text(text)
    print("wrote", s["name"])
print(len(SYMS) + len(MORE), "total")
