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
from ..writers.xschem import SCALE, sym_path, transform

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


def _reverse_map(registry: SymbolRegistry) -> dict[str, list[tuple[str, dict]]]:
    """xschem sym path -> [(registry symbol, effective xschem meta)].
    Primary paths and aliases both resolve; several macros share one .sym
    (vnmos/vmnmos/lvnmos...), so candidates are kept sorted with the
    shortest name first and disambiguated by rot/flip at the call site."""
    table: dict[str, list[tuple[str, dict]]] = {}
    for name in registry.names():
        sym = registry.get(name)
        meta = dict(sym.xschem or {})
        aliases = meta.pop("aliases", {}) or {}
        table.setdefault(sym_path(sym), []).append((name, meta))
        for path, overrides in aliases.items():
            table.setdefault(path, []).append((name, {**meta, **(overrides or {})}))
    for cands in table.values():
        cands.sort(key=lambda c: (len(c[0]), c[0]))
    return table


def _pick_variant(cands: list[tuple[str, dict]], rot: int, flip: int):
    """Prefer the variant whose baked-in rot/flip matches the instance
    (vmnmos for a flipped nfet, hresistor for a rot-1 res)."""
    for name, meta in cands:
        if meta.get("rot", 0) == rot and meta.get("flip", 0) == flip:
            return name, meta, True
    return (*cands[0], False)


def read_sym_geometry(path: Path) -> dict:
    """Bounding box and pin positions of a .sym file, in raw xschem units
    (y down, untransformed): {"bbox": [x1,y1,x2,y2], "pins": {name: [x,y]}}."""
    xs, ys = [], []
    pins = {}
    for tag, fields in _tokens(path.read_text()):
        if tag == "B" and fields[0][1] == "5":
            x1, y1, x2, y2 = (float(f[1]) for f in fields[1:5])
            props = _props(fields[5][1]) if len(fields) > 5 else {}
            pins[props.get("name", f"p{len(pins)}")] = [(x1 + x2) / 2, (y1 + y2) / 2]
        elif tag in ("L", "B"):
            xs += [float(fields[1][1]), float(fields[3][1])]
            ys += [float(fields[2][1]), float(fields[4][1])]
        elif tag == "P" and len(fields) >= 2:
            n = int(fields[1][1])
            coords = [float(f[1]) for f in fields[2 : 2 + 2 * n]]
            xs += coords[0::2]
            ys += coords[1::2]
    if not xs:
        xs, ys = [-20, 20], [-20, 20]
    return {"bbox": [min(xs), min(ys), max(xs), max(ys)], "pins": pins}


def read_sch(
    source: str | Path,
    registry: SymbolRegistry | None = None,
    sym_dirs: list[Path] | None = None,
    keep_labels: bool = False,
) -> Schematic:
    """Parse .sch text (or a path to it) into a Schematic.

    sym_dirs: directories to resolve foreign .sym references against; a
    resolved symbol keeps its real bounding box and pin positions, so
    the TikZ writer reproduces the original placement instead of a
    generic box. keep_labels: emit lab_pin markers as visible Labels
    (positional conversions want the net names where the author put
    them)."""
    registry = registry or SymbolRegistry.load()
    path = Path(source) if not str(source).lstrip().startswith("v {") else None
    text = path.read_text() if path else str(source)
    name = path.stem if path else "schematic"

    sch = Schematic(name)
    rev = _reverse_map(registry)
    labels_at: list[tuple[float, float, str]] = []  # lab_pin positions, xschem units
    inst_meta: dict[str, dict] = {}  # instance -> effective xschem meta + placement

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
                labels_at.append((x, y, props.get("lab", "")))
                if keep_labels:
                    # above the wire point, like xschem draws it
                    sch.add(Label(props.get("lab", ""), pos=(fx, fy), anchor="south"))
            elif sym.startswith("cborder/") or sym.endswith("/title.sym"):
                pass  # sheet frame furniture, not circuit
            elif sym in PORT_DIRECTION:
                sch.add(Port(props.get("lab", ""), pos=(fx, fy),
                             direction=PORT_DIRECTION[sym]))
            elif sym in rev:
                name_, meta, matched = _pick_variant(rev[sym], rot, flip)
                ox, oy = meta.get("origin", (0, 0))
                inst = Instance(
                    props.get("name", f"X{len(sch.instances) + 1}"), name_,
                    pos=(round(fx - ox, 6), round(fy - oy, 6)),
                    # a matched variant absorbs the instance transform
                    rot=0 if matched else rot,
                    flip=False if matched else bool(flip),
                )
                sch.add(inst)
                inst_meta[inst.name] = {**meta, "xy": (x, y), "rot": rot, "flip": flip}
            else:
                geom = None
                for d in sym_dirs or []:
                    cand = Path(d).expanduser() / sym
                    if cand.exists():
                        geom = read_sym_geometry(cand)
                        break
                sch.add(Instance(props.get("name", f"X{len(sch.instances) + 1}"),
                                 f"unknown:{sym}", pos=(fx, fy), rot=rot,
                                 flip=bool(flip), geom=geom))
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

    _attach_labels(sch, labels_at, inst_meta, registry)
    return sch


def _xschem_pin_points(sch, inst_meta, registry):
    """(instance, pin) -> xschem-space position, using verified pin_xy
    geometry where available and TikZ grid geometry as the fallback."""
    points = {}
    for inst in sch.instances:
        if inst.symbol.startswith("unknown:"):
            continue
        sym = registry.get(inst.symbol)
        meta = inst_meta.get(inst.name, {})
        pin_xy = meta.get("pin_xy", {})
        for p in sym.pins:
            if p.name in pin_xy:
                x0, y0 = meta["xy"]
                dx, dy = transform(
                    *pin_xy[p.name], meta.get("rot", 0), meta.get("flip", 0)
                )
                points[(inst.name, p.name)] = (x0 + dx, y0 + dy)
            else:
                points[(inst.name, p.name)] = (
                    (inst.pos[0] + p.grid_xy[0]) * SCALE,
                    -(inst.pos[1] + p.grid_xy[1]) * SCALE,
                )
    return points


def _attach_labels(sch, labels_at, inst_meta, registry):
    """Turn lab_pin markers into conns on the nearest coincident pin and
    net names on coincident wire endpoints. Comparison happens in xschem
    units with one grid-snap of slack."""
    snap = PIN_SNAP * SCALE
    points = _xschem_pin_points(sch, inst_meta, registry)
    for lx, ly, net in labels_at:
        for (iname, pname), (px, py) in points.items():
            if abs(px - lx) <= snap and abs(py - ly) <= snap:
                inst = next(i for i in sch.instances if i.name == iname)
                inst.conns.setdefault(pname, net)
        for wire in sch.wires:
            if wire.net:
                continue
            for wx, wy in (wire.points[0], wire.points[-1]):
                if abs(wx * SCALE - lx) <= snap and abs(-wy * SCALE - ly) <= snap:
                    wire.net = net
