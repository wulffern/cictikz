"""Schematic IR -> xschem .sch.

Connectivity uses the lab_pin trick (from cicpy's xschemprinter): every
connected pin gets a ``devices/lab_pin.sym`` instance carrying the net
name at the pin position, so no wires need routing — xschem netlists by
label. Generated schematics are electrically correct, not pretty.

Figure units map to xschem units by SCALE (default 40, so the 1.6 grid
becomes 64) with y flipped (xschem y grows downward) and everything
snapped to 10.
"""

from __future__ import annotations

from ..schematic import Schematic
from ..symbols import SymbolDef, SymbolRegistry

SCALE = 40

HEADER = """v {xschem version=3.0.0 file_version=1.2 }
G {}
K {}
V {}
S {}
E {}
"""

PORT_SYM = {"in": "devices/ipin.sym", "out": "devices/opin.sym", "inout": "devices/iopin.sym"}


def _u(v: float) -> int:
    """Figure units -> snapped xschem units."""
    return int(round(v * SCALE / 10.0) * 10)


def _xy(p: tuple[float, float]) -> tuple[int, int]:
    return _u(p[0]), -_u(p[1])


def sym_path(sym: SymbolDef) -> str:
    """The .sym file an instance of this symbol references."""
    if sym.xschem and sym.xschem.get("sym"):
        return sym.xschem["sym"]
    return f"cictikz/{sym.name}.sym"


def write_sch(sch: Schematic, registry: SymbolRegistry | None = None) -> str:
    registry = registry or SymbolRegistry.load()
    out = [HEADER]
    nlab = 0

    for inst in sch.instances:
        sym = registry.get(inst.symbol)
        x, y = _xy(inst.pos)
        rot = inst.rot % 4
        flip = 1 if inst.flip else 0
        out.append(f"C {{{sym_path(sym)}}} {x} {y} {rot} {flip} {{name={inst.name}}}")
        pins = {p.name: p for p in sym.pins}
        for pin, net in inst.conns.items():
            if pin not in pins:
                raise ValueError(
                    f"{inst.name}: symbol '{sym.name}' has no pin '{pin}' "
                    f"(pins: {', '.join(pins)})"
                )
            px, py = _xy(
                (inst.pos[0] + pins[pin].grid_xy[0], inst.pos[1] + pins[pin].grid_xy[1])
            )
            nlab += 1
            out.append(
                f"C {{devices/lab_pin.sym}} {px} {py} 0 0 {{name=l{nlab} lab={net}}}"
            )

    for i, port in enumerate(sch.ports, start=1):
        x, y = _xy(port.pos)
        out.append(
            f"C {{{PORT_SYM[port.direction]}}} {x} {y} 0 0 {{name=p{i} lab={port.net}}}"
        )

    for wire in sch.wires:
        if wire.net is None:
            continue
        for a, b in zip(wire.points, wire.points[1:]):
            (x1, y1), (x2, y2) = _xy(a), _xy(b)
            out.append(f"N {x1} {y1} {x2} {y2} {{lab={wire.net}}}")

    return "\n".join(out) + "\n"
