"""The cictikz schematic IR.

A small structural model that sits between the backends: build it from
Python or JSON, write it out as dialect TikZ or xschem .sch (phase 2),
read it back from either (phase 3). Coordinates are figure units
(\\grid = 1.6), y up, like the symbol metadata.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SNAP = 0.05  # coordinate coincidence tolerance for net derivation


@dataclass
class Instance:
    name: str
    symbol: str  # registry name, e.g. "lvnmos"
    pos: tuple[float, float] = (0, 0)
    args: list[str] = field(default_factory=list)  # macro arguments; defaults applied by writers
    rot: int = 0  # quarter turns CCW (xschem backend only; TikZ macros do not rotate)
    flip: bool = False
    conns: dict[str, str] = field(default_factory=dict)  # pin name -> net name


@dataclass
class Wire:
    points: list[tuple[float, float]]
    net: str | None = None


@dataclass
class Label:
    text: str
    pos: tuple[float, float]
    anchor: str = "center"


@dataclass
class Port:
    net: str
    pos: tuple[float, float]
    direction: str = "in"  # in | out | inout


@dataclass
class Schematic:
    name: str
    instances: list[Instance] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    ports: list[Port] = field(default_factory=list)

    def add(self, item):
        {Instance: self.instances, Wire: self.wires,
         Label: self.labels, Port: self.ports}[type(item)].append(item)
        return item

    def pin_points(self, registry) -> dict[tuple[str, str], tuple[float, float]]:
        """(instance, pin) -> absolute position, from the symbol metadata."""
        points = {}
        for inst in self.instances:
            sym = registry.get(inst.symbol)
            for p in sym.pins:
                points[(inst.name, p.name)] = (
                    inst.pos[0] + p.grid_xy[0],
                    inst.pos[1] + p.grid_xy[1],
                )
        return points

    def nets(self, registry) -> dict[str, list[tuple[str, str]]]:
        """net -> [(instance, pin)], from explicit conns plus wire endpoints
        that coincide (within SNAP) with a pin of a named-net wire."""
        result: dict[str, list[tuple[str, str]]] = {}
        for inst in self.instances:
            for pin, net in inst.conns.items():
                result.setdefault(net, []).append((inst.name, pin))
        points = self.pin_points(registry)
        for wire in self.wires:
            if wire.net is None:
                continue
            for wx, wy in (wire.points[0], wire.points[-1]):
                for (iname, pname), (px, py) in points.items():
                    if abs(px - wx) <= SNAP and abs(py - wy) <= SNAP:
                        entry = (iname, pname)
                        if entry not in result.setdefault(wire.net, []):
                            result[wire.net].append(entry)
        return result

    # -- JSON ----------------------------------------------------------
    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Schematic":
        allowed = {
            "instances": {f for f in Instance.__dataclass_fields__},
            "wires": {f for f in Wire.__dataclass_fields__},
            "labels": {f for f in Label.__dataclass_fields__},
            "ports": {f for f in Port.__dataclass_fields__},
        }
        for kind, items in allowed.items():
            for entry in d.get(kind, []):
                unknown = set(entry) - items
                if unknown:
                    raise TypeError(f"unknown {kind[:-1]} keys: {sorted(unknown)}")
        sch = cls(name=d["name"])
        for e in d.get("instances", []):
            e = dict(e, pos=tuple(e.get("pos", (0, 0))))
            sch.instances.append(Instance(**e))
        for e in d.get("wires", []):
            sch.wires.append(Wire(points=[tuple(p) for p in e["points"]], net=e.get("net")))
        for e in d.get("labels", []):
            sch.labels.append(Label(**dict(e, pos=tuple(e["pos"]))))
        for e in d.get("ports", []):
            sch.ports.append(Port(**dict(e, pos=tuple(e["pos"]))))
        return sch
