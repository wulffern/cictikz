"""Symbol metadata registry.

One YAML per symbol under ``data/symbols/``; geometry is in grid units
(``\\grid`` = 1.6, one transistor tall, y up) relative to the macro's
entry point, so both the TikZ and xschem backends can reason about pin
positions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources

import yaml


@dataclass(frozen=True)
class PinDef:
    name: str
    grid_xy: tuple[float, float]
    direction: str  # in | out | inout | supply


@dataclass(frozen=True)
class SymbolDef:
    name: str
    macro: str
    nargs: int
    arg_doc: list[str]
    description: str
    entry: tuple[float, float]
    exit: tuple[float, float]
    height_grid: float
    width_grid: float
    pins: list[PinDef]
    example: str
    nodes: list[str] = field(default_factory=list)  # circuitikz anchors, e.g. M1.gate
    xschem: dict | None = None  # {sym, pin_map, scale}

    def signature(self) -> str:
        args = "".join("{%s}" % d for d in self.arg_doc) if self.nargs else ""
        return f"{self.macro}{args}"


def _load_one(text: str) -> SymbolDef:
    d = yaml.safe_load(text)
    pins = [
        PinDef(p["name"], tuple(p["grid_xy"]), p.get("direction", "inout"))
        for p in d.get("pins", [])
    ]
    return SymbolDef(
        name=d["name"],
        macro=d["macro"],
        nargs=d.get("nargs", 0),
        arg_doc=d.get("arg_doc", []),
        description=d.get("description", ""),
        entry=tuple(d.get("entry", [0, 0])),
        exit=tuple(d.get("exit", [0, 0])),
        height_grid=d.get("height_grid", 0),
        width_grid=d.get("width_grid", 0),
        pins=pins,
        example=d.get("example", ""),
        nodes=d.get("nodes", []),
        xschem=d.get("xschem"),
    )


class SymbolRegistry:
    def __init__(self, symbols: dict[str, SymbolDef]):
        self._symbols = symbols

    @classmethod
    def load(cls) -> "SymbolRegistry":
        symbols = {}
        root = resources.files("cictikz") / "data" / "symbols"
        for entry in sorted(root.iterdir(), key=lambda e: e.name):
            if entry.name.endswith(".yaml"):
                sd = _load_one(entry.read_text())
                symbols[sd.name] = sd
        return cls(symbols)

    def names(self) -> list[str]:
        return sorted(self._symbols)

    def get(self, name: str) -> SymbolDef:
        try:
            return self._symbols[name.lstrip("\\")]
        except KeyError:
            raise KeyError(
                f"unknown symbol '{name}' - known: {', '.join(self.names())}"
            ) from None

    def search(self, query: str = "") -> list[SymbolDef]:
        q = query.lower()
        return [
            s
            for name, s in sorted(self._symbols.items())
            if q in name.lower() or q in s.description.lower()
        ]
