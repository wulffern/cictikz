"""Generate xschem .sym files for cictikz-only symbols (OTA outlines,
current mirrors, ...) from the same YAML pin geometry the TikZ side
uses, so both backends agree on where pins are.

Record grammar follows cicpy's xschemprinter: layer 5 boxes are pins,
layer 4 lines are pin stubs, a layer 4 polygon is the body outline,
``T`` records are text, and the ``K`` block declares the subcircuit
format/template.
"""

from __future__ import annotations

from pathlib import Path

from ..symbols import SymbolDef, SymbolRegistry
from .xschem import _u, _xy

HEADER = """v {xschem version=3.0.0 file_version=1.2 }
G {}
K {type=subcircuit
format="@name @pinlist @symname"
template="name=x1"
}
V {}
S {}
E {}
"""


def write_sym(sym: SymbolDef) -> str:
    out = [HEADER]
    # Body outline: the symbol's bounding box in xschem units.
    xs = [p.grid_xy[0] for p in sym.pins] or [0]
    ys = [p.grid_xy[1] for p in sym.pins] or [0]
    x1, x2 = _u(min(xs)), _u(max(xs))
    y1, y2 = -_u(max(ys)), -_u(min(ys))
    if x1 == x2:
        x1, x2 = x1 - 10, x2 + 10
    if y1 == y2:
        y1, y2 = y1 - 10, y2 + 10
    out.append(
        f"P 4 5 {x1} {y1} {x2} {y1} {x2} {y2} {x1} {y2} {x1} {y1} {{}}"
    )
    out.append(f"T {{@symname}} {x1} {y1 - 30} 0 0 0.25 0.25 {{}}")
    out.append(f"T {{@name}} {x2} {y2 + 10} 0 0 0.2 0.2 {{}}")
    for p in sym.pins:
        px, py = _xy(p.grid_xy)
        direction = {"supply": "inout"}.get(p.direction, p.direction)
        out.append(
            f"B 5 {px - 2.5} {py - 2.5} {px + 2.5} {py + 2.5} "
            f"{{name={p.name} dir={direction}}}"
        )
        out.append(f"T {{{p.name}}} {px + 5} {py - 5} 0 0 0.2 0.2 {{}}")
    return "\n".join(out) + "\n"


def export_symlib(outdir: Path, registry: SymbolRegistry | None = None) -> list[Path]:
    """Write cictikz/<name>.sym for every symbol without a standard-library
    xschem mapping. Returns the written paths."""
    registry = registry or SymbolRegistry.load()
    outdir = Path(outdir) / "cictikz"
    outdir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in registry.names():
        sym = registry.get(name)
        if sym.xschem and sym.xschem.get("sym"):
            continue
        path = outdir / f"{name}.sym"
        path.write_text(write_sym(sym))
        written.append(path)
    return written
