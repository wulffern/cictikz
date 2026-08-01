"""xschem .sch -> Schematic IR.

Works on any xschem schematic, not just cictikz-generated ones:
recognised symbol paths map back to registry symbols, lab_pin/ipin/
opin/iopin become connectivity, N records become wires, and instances
of unknown symbols are kept opaque as ``unknown:<path>`` so they
round-trip back to xschem losslessly (the TikZ writer draws them as a
labelled box).
"""

from __future__ import annotations

import re
from pathlib import Path

from ..schematic import Instance, Label, Port, Schematic, Wire
from ..symbols import SymbolRegistry
from ..writers.xschem import SCALE, sym_path

PIN_SNAP = 12 / SCALE  # one xschem grid-snap of slack when attaching labels

PORT_DIRECTION = {
    "devices/ipin.sym": "in",
    "devices/opin.sym": "out",
    "devices/iopin.sym": "inout",
}


class SchParseError(ValueError):
    pass


def _tokens(text: str):
    """Yield (tag, fields) per record; {...} blocks are brace-matched so
    multi-line property strings stay one field."""
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            return
        tag = text[i]
        i += 1
        fields = []
        while i < n:
            while i < n and text[i] in " \t":
                i += 1
            if i >= n or text[i] == "\n":
                break
            if text[i] == "{":
                depth, start = 1, i + 1
                i += 1
                while i < n and depth:
                    if text[i] == "{":
                        depth += 1
                    elif text[i] == "}":
                        depth -= 1
                    i += 1
                if depth:
                    raise SchParseError("unbalanced braces")
                fields.append(("{}", text[start : i - 1]))
            else:
                start = i
                while i < n and text[i] not in " \t\n":
                    i += 1
                fields.append(("w", text[start:i]))
        yield tag, fields


def _props(raw: str) -> dict[str, str]:
    return dict(re.findall(r"(\w+)=(\S+)", raw))


def _reverse_map(registry: SymbolRegistry) -> dict[str, str]:
    """xschem sym path -> canonical registry symbol. Several macros share
    one .sym (vnmos/vmnmos/lvnmos...); the shortest name wins so a plain
    nfet comes back as vnmos, not lvmnmos."""
    table: dict[str, str] = {}
    for name in registry.names():
        path = sym_path(registry.get(name))
        if path not in table or (len(name), name) < (len(table[path]), table[path]):
            table[path] = name
    return table


def read_sch(source: str | Path, registry: SymbolRegistry | None = None) -> Schematic:
    """Parse .sch text (or a path to it) into a Schematic."""
    registry = registry or SymbolRegistry.load()
    path = Path(source) if not str(source).lstrip().startswith("v {") else None
    text = path.read_text() if path else str(source)
    name = path.stem if path else "schematic"

    sch = Schematic(name)
    rev = _reverse_map(registry)
    labels_at: list[tuple[float, float, str]] = []  # lab_pin positions, figure units

    for tag, fields in _tokens(text):
        if tag == "C":
            sym, x, y, rot, flip, props = (
                fields[0][1],
                float(fields[1][1]),
                float(fields[2][1]),
                int(fields[3][1]),
                int(float(fields[4][1])),
                _props(fields[5][1]) if len(fields) > 5 else {},
            )
            fx, fy = x / SCALE, -y / SCALE
            if sym == "devices/lab_pin.sym" or sym == "devices/lab_wire.sym":
                labels_at.append((fx, fy, props.get("lab", "")))
            elif sym in PORT_DIRECTION:
                sch.add(Port(props.get("lab", ""), pos=(fx, fy),
                             direction=PORT_DIRECTION[sym]))
            elif sym in rev:
                sch.add(Instance(props.get("name", f"X{len(sch.instances) + 1}"),
                                 rev[sym], pos=(fx, fy), rot=rot, flip=bool(flip)))
            else:
                sch.add(Instance(props.get("name", f"X{len(sch.instances) + 1}"),
                                 f"unknown:{sym}", pos=(fx, fy), rot=rot,
                                 flip=bool(flip)))
        elif tag == "N":
            x1, y1, x2, y2 = (float(f[1]) for f in fields[:4])
            props = _props(fields[4][1]) if len(fields) > 4 else {}
            sch.add(Wire(points=[(x1 / SCALE, -y1 / SCALE), (x2 / SCALE, -y2 / SCALE)],
                         net=props.get("lab")))
        elif tag == "T":
            text_, x, y = fields[0][1], float(fields[1][1]), float(fields[2][1])
            if not text_.startswith("@"):
                sch.add(Label(text_, pos=(x / SCALE, -y / SCALE)))
        # v/G/K/V/S/E/B/L/P records carry no schematic content we keep.

    _attach_labels(sch, labels_at, registry)
    return sch


def _attach_labels(sch, labels_at, registry):
    """Turn lab_pin markers into conns on the nearest coincident pin and
    net names on coincident wire endpoints."""
    points = sch.pin_points(registry)
    for lx, ly, net in labels_at:
        for (iname, pname), (px, py) in points.items():
            if abs(px - lx) <= PIN_SNAP and abs(py - ly) <= PIN_SNAP:
                inst = next(i for i in sch.instances if i.name == iname)
                inst.conns.setdefault(pname, net)
        for wire in sch.wires:
            if wire.net:
                continue
            for wx, wy in (wire.points[0], wire.points[-1]):
                if abs(wx - lx) <= PIN_SNAP and abs(wy - ly) <= PIN_SNAP:
                    wire.net = net
