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
    # For unknown:* symbols whose .sym file was resolved: raw xschem-unit
    # geometry {"bbox": [x1,y1,x2,y2], "pins": {name: [x,y]}}, so writers
    # can draw a true-sized box with pins where the original put them.
    geom: dict | None = None


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
            if inst.symbol.startswith("unknown:"):
                continue  # opaque foreign symbol: no pin metadata
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

    def infer_nets(self, registry) -> None:
        """Derive connectivity from geometry: pins, wire endpoints and
        ports that coincide (within SNAP) are one electrical node. Named
        groups take their name from a port, then an explicit conn, then
        the wire's net; anonymous groups get net1, net2, ... Fills in
        inst.conns and wire.net in place."""

        def key(p):
            return (round(p[0] / SNAP), round(p[1] / SNAP))

        parent: dict = {}

        def find(a):
            parent.setdefault(a, a)
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        def union(a, b):
            parent[find(a)] = find(b)

        pin_pts = self.pin_points(registry)
        for (iname, pname), p in pin_pts.items():
            find(("pin", iname, pname))
            union(("pin", iname, pname), ("pt", key(p)))
        for wi, wire in enumerate(self.wires):
            find(("wire", wi))
            for p in wire.points:
                union(("wire", wi), ("pt", key(p)))
        for port in self.ports:
            union(("port", port.net), ("pt", key(port.pos)))

        names: dict = {}
        for port in self.ports:
            names[find(("port", port.net))] = port.net
        # Supply symbols name their whole net (vground -> GND, vsupply -> VDD)
        for inst in self.instances:
            if inst.symbol.startswith("unknown:"):
                continue
            net = (registry.get(inst.symbol).xschem or {}).get("net")
            if net:
                for p in registry.get(inst.symbol).pins:
                    names.setdefault(find(("pin", inst.name, p.name)), net)
        for inst in self.instances:
            for pname, net in inst.conns.items():
                names.setdefault(find(("pin", inst.name, pname)), net)
        for wi, wire in enumerate(self.wires):
            if wire.net:
                names.setdefault(find(("wire", wi)), wire.net)

        counter = 0
        def name_of(root):
            nonlocal counter
            if root not in names:
                counter += 1
                names[root] = f"net{counter}"
            return names[root]

        # a pin deserves a net name when anything else shares its group:
        # another pin (stacked devices abut), a wire, or a port
        members: dict = {}
        for iname, pname in pin_pts:
            members.setdefault(find(("pin", iname, pname)), []).append(1)
        for wi in range(len(self.wires)):
            members.setdefault(find(("wire", wi)), []).append(1)
        for port in self.ports:
            members.setdefault(find(("port", port.net)), []).append(1)

        for inst in self.instances:
            for (iname, pname), p in pin_pts.items():
                if iname != inst.name or pname in inst.conns:
                    continue
                root = find(("pin", iname, pname))
                if root in names or len(members.get(root, [])) >= 2:
                    inst.conns[pname] = name_of(root)
        for wi, wire in enumerate(self.wires):
            if wire.net is None:
                wire.net = name_of(find(("wire", wi)))

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
