"""Read an xschem `.sym` file and draw it in TikZ.

The point is not to import arbitrary artwork. It is that a course draws
the same cell twice - once as the symbol a student places in xschem, and
once as the figure in the book - and the two ought to be the same shape.
Deriving the figure from the symbol makes that true by construction
rather than by eye.

The format is a line per record:

    L layer x1 y1 x2 y2 {}          a line
    P layer n x1 y1 x2 y2 ... {}    a polygon
    A layer x y r start extent {}   an arc, degrees, counterclockwise
    B layer x1 y1 x2 y2 {name=A …}  a pin, as a small box
    T {text} x y rot flip w h {}    a label

xschem's y axis points down, so everything is flipped on the way out.
Coordinates are scaled so the symbol lands on the house grid: the
default puts a standard cell's 40-unit body at 1.1, the height the
hand-drawn logic in this library already uses.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

# One xschem unit in figure units. A JNW standard cell's triangle is 40
# tall, and the library's hand-drawn one is 1.1, so 1.1/40 keeps a
# converted symbol the same size as the symbols beside it.
SCALE = 1.1 / 40


@dataclass
class Symbol:
    name: str
    lines: list[tuple[float, float, float, float]] = field(default_factory=list)
    arcs: list[tuple[float, float, float, float, float]] = field(default_factory=list)
    polys: list[list[tuple[float, float]]] = field(default_factory=list)
    pins: dict[str, tuple[float, float]] = field(default_factory=dict)
    labels: list[tuple[float, float, str]] = field(default_factory=list)

    def extent(self) -> tuple[float, float, float, float]:
        xs, ys = [], []
        for x1, y1, x2, y2 in self.lines:
            xs += [x1, x2]
            ys += [y1, y2]
        for x, y, r, _, _ in self.arcs:
            xs += [x - r, x + r]
            ys += [y - r, y + r]
        for poly in self.polys:
            xs += [p[0] for p in poly]
            ys += [p[1] for p in poly]
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))


_NUM = r"-?[\d.]+"
_L = re.compile(rf"^L\s+\d+\s+({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})")
_A = re.compile(rf"^A\s+\d+\s+({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})")
_B = re.compile(rf"^B\s+\d+\s+({_NUM})\s+({_NUM})\s+({_NUM})\s+({_NUM})\s+\{{(.*)\}}")
_P = re.compile(rf"^P\s+\d+\s+(\d+)\s+(.*?)\{{")
_T = re.compile(rf"^T\s+\{{(.*?)\}}\s+({_NUM})\s+({_NUM})")


def parse_sym(text: str, name: str = "sym", scale: float = SCALE) -> Symbol:
    """Read the records. y is negated: xschem counts downwards."""
    sym = Symbol(name=name)

    def pt(x, y):
        return (float(x) * scale, -float(y) * scale)

    for line in text.splitlines():
        line = line.strip()
        m = _L.match(line)
        if m:
            x1, y1 = pt(m.group(1), m.group(2))
            x2, y2 = pt(m.group(3), m.group(4))
            sym.lines.append((x1, y1, x2, y2))
            continue
        m = _A.match(line)
        if m:
            x, y = pt(m.group(1), m.group(2))
            r = float(m.group(3)) * scale
            # The y flip reverses the sweep direction as well.
            start, extent = -float(m.group(4)), -float(m.group(5))
            sym.arcs.append((x, y, r, start, extent))
            continue
        m = _B.match(line)
        if m:
            x1, y1 = pt(m.group(1), m.group(2))
            x2, y2 = pt(m.group(3), m.group(4))
            attrs = m.group(5)
            pin = re.search(r"name=(\w+)", attrs)
            if pin:
                sym.pins[pin.group(1)] = ((x1 + x2) / 2, (y1 + y2) / 2)
            continue
        m = _P.match(line)
        if m:
            nums = [float(v) for v in re.findall(_NUM, m.group(2))]
            poly = [(nums[i] * scale, -nums[i + 1] * scale)
                    for i in range(0, len(nums) - 1, 2)]
            if poly:
                sym.polys.append(poly)
            continue
        m = _T.match(line)
        if m:
            label = m.group(1)
            # @name and @symname are xschem's own substitutions, not
            # anything a figure wants printed.
            if label.startswith("@"):
                continue
            x, y = pt(m.group(2), m.group(3))
            sym.labels.append((x, y, label))
    return sym


_DIGITS = {"0": "Zero", "1": "One", "2": "Two", "3": "Three", "4": "Four",
           "5": "Five", "6": "Six", "7": "Seven", "8": "Eight", "9": "Nine"}


def _sanitise(name: str) -> str:
    """A macro name TeX will accept: letters, nothing else."""
    out = []
    for ch in name:
        if ch.isalpha():
            out.append(ch)
        elif ch in _DIGITS:
            out.append(_DIGITS[ch])
    return "".join(out) or "cicSym"


def _fmt(v: float) -> str:
    return f"{v:.5g}"


def to_tikz(sym: Symbol, macro: str | None = None, labels: bool = False) -> str:
    """Emit the symbol as a TikZ path-fragment macro.

    The macro follows the library's convention: it starts at the current
    point, draws, and exports the pins as coordinates named after the
    instance, so it chains like every other symbol here.
    """
    # A TeX control sequence is letters only: JNWATR_NCH_4C5F0 cannot be
    # a macro name, and TeX's complaint about it ("Missing number") says
    # nothing about where it came from.
    macro = _sanitise(macro or "cic" + sym.name.title())
    out = [f"% Generated from {sym.name}.sym - edit the symbol, not this file.",
           f"\\newcommand{{\\{macro}}}[1]{{",
           "  ++(0,0) coordinate (#1_org)"]
    for x1, y1, x2, y2 in sym.lines:
        out.append(f"  (#1_org) ++({_fmt(x1)},{_fmt(y1)})"
                   f" -- ++({_fmt(x2 - x1)},{_fmt(y2 - y1)})")
    for x, y, r, start, extent in sym.arcs:
        if abs(extent) >= 359:
            out.append(f"  (#1_org) ++({_fmt(x)},{_fmt(y)}) circle ({_fmt(r)})")
        else:
            # TikZ's arc begins at the current point and reads it as
            # the point at the start angle, so the pen has to be put
            # there first - not at (r,0), which is only that point when
            # the arc happens to start at zero degrees.
            dx = r * math.cos(math.radians(start))
            dy = r * math.sin(math.radians(start))
            out.append(f"  (#1_org) ++({_fmt(x)},{_fmt(y)})"
                       f" ++({_fmt(dx)},{_fmt(dy)})"
                       f" arc ({_fmt(start)}:{_fmt(start + extent)}:{_fmt(r)})")
    for poly in sym.polys:
        first = poly[0]
        path = f"  (#1_org) ++({_fmt(first[0])},{_fmt(first[1])})"
        for x, y in poly[1:]:
            path += f" -- ++({_fmt(x - first[0])},{_fmt(y - first[1])})"
            first = (x, y)
        out.append(path)
    if labels:
        for x, y, text in sym.labels:
            out.append(f"  (#1_org) ++({_fmt(x)},{_fmt(y)})"
                       f" node[scale=0.7] {{{text}}}")
    for pin, (x, y) in sym.pins.items():
        out.append(f"  (#1_org) ++({_fmt(x)},{_fmt(y)}) coordinate (#1_{pin.lower()})")
    out.append("  (#1_org)")
    out.append("}")
    return "\n".join(out)


def convert(path: str | Path, macro: str | None = None,
            labels: bool = False, scale: float = SCALE) -> str:
    path = Path(path)
    sym = parse_sym(path.read_text(), path.stem, scale)
    return to_tikz(sym, macro, labels)
