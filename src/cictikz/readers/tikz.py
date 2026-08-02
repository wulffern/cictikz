"""Constrained cictikz-dialect TikZ -> Schematic IR.

This reads figures written in the cictikz macro vocabulary — what
write_tikz emits, and hand figures that stay inside the dialect:
``\\draw`` paths made of absolute/relative moves, named coordinates,
registry macros, ``--`` / ``|-`` / ``-|`` / ``to[short]`` segments,
``\\node`` labels and ``\\fill`` junction dots. Anything else raises
DialectError with the line number: this is deliberately NOT a TikZ
parser, and pretending to read arbitrary TikZ would produce silently
wrong schematics.

Macro instances register their pin anchors, so ``(M1.drain)`` resolves
through the same YAML geometry the writers use.
"""

from __future__ import annotations

import re
from functools import lru_cache

from ..schematic import Instance, Label, Port, Schematic, Wire
from ..symbols import SymbolRegistry

PORT_MACROS = {"portIn": "in", "portmIn": "in", "portOut": "out"}

# Element bipoles the library has no macro for; they stay circuitikz and
# round-trip verbatim as bipole: instances.
_ELEMENT_BIPOLES = {"I", "cI", "sI", "V", "sV", "cV", "L", "full diode",
                    "battery", "sqV", "vsourcesin"}

# A coordinate component: a number or arithmetic on numbers, braced or
# bare - TikZ allows both (0,\grid/4) and ({\grid+0.5},0), and constants
# (\grid, local \newcommand values) are substituted before tokenizing.
_EXPR = r"(?:\{[\d.+\-*/() ]+\}|[-+]?[\d.][\d.+\-*/()]*)"

# Text that may contain one level of nested braces: {$V_{DD}$}.
_NEST = r"(?:[^{}]|\{[^{}]*\})*"

_TOKEN = re.compile(
    rf"""\s*(?:
      (?P<rel>\+\+?\(\s*(?P<rx>{_EXPR})\s*,\s*(?P<ry>{_EXPR})\s*\))
    | (?P<abs>\(\s*(?P<ax>{_EXPR})\s*,\s*(?P<ay>{_EXPR})\s*\))
    | (?P<named>\(\s*(?P<nref>[A-Za-z][\w.$\\ ]*?)\s*\))
    | (?P<coord>coordinate\s*\(\s*(?P<cname>[\w.]+)\s*\))
    | (?P<to>to\s*\[(?P<toopts>[^\]]*)\])
    | (?P<conn>--|\|-|-\|)
    | (?P<node>node\s*(?:\[(?P<nopts>[^\]]*)\])?\s*\{{(?P<ntext>{_NEST})\}})
    | (?P<circle>circle\s*\(\s*[\d.]+\s*\))
    | (?P<cycle>cycle\b)
    | (?P<rect>rectangle\b)
    | (?P<opts>\[(?P<popts>[^\]]*)\])
    | (?P<macro>\\(?P<mname>[A-Za-z]+))
    )""",
    re.VERBOSE,
)

# Cosmetic options carry no structure and are accepted then ignored;
# anything else (component shapes like [pnp], calc, plots) is rejected.
_COSMETIC = re.compile(
    r"""^(
      |(black|red|blue|armygreen|white|poly|active|cut|mOne|mTwo|mThree
        |mFour|echarge|hcharge|gray|orange)(!\d+)?(!\w+)?
      |label(=[^,]*)?
      |(densely\ |loosely\ )?(dashed|dotted)
      |thin|thick|very\ thick|ultra\ thick
      |rounded\ corners(=[^,]*)?
      |->|<-|<->
      |(color|fill|draw|opacity|anchor|rotate|scale|align|font|text\ width
        |inner\ sep|outer\ sep|xshift|yshift|shift|minimum\ width
        |minimum\ height|minimum\ size|pos|midway|above|below|left|right)((=| )[^,]*)?
    )$""",
    re.VERBOSE,
)


def _num(expr: str) -> float:
    """Evaluate a coordinate component: arithmetic on numbers, braced or bare."""
    expr = expr.strip()
    if expr.startswith("{"):
        expr = expr[1:-1]
    if not re.fullmatch(r"[\d.+\-*/() ]+", expr):
        raise ValueError(f"bad expression {expr}")
    return float(eval(expr, {"__builtins__": {}}, {}))  # arithmetic only, vetted by regex


#- Colour names the current figure defines with \definecolor; they are
#  as cosmetic as the built-in palette. Set per read_tikz call.
_local_colours: set = set()


def _check_style(opts: str | None, line: int, what: str):
    for opt in (opts or "").split(","):
        o = opt.strip()
        if _COSMETIC.fullmatch(o):
            continue
        base = o.split("!", 1)[0].split("=", 1)[0].strip()
        if base in _local_colours:
            continue
        raise DialectError(f"{what} option '{o}' outside dialect", line)
    return (opts or "")

_STMT = re.compile(r"\\(draw|fill|node|path)\b([^;]*);", re.DOTALL)

_ALLOWED_TO = re.compile(r"^(short|-o?|o-|\*-o?|o?-\*|i[<>_^]?=[^,]*|l_?=[^,]*|\s*)$")


@lru_cache(maxsize=1)
def _lib_constants() -> dict[str, str]:
    """Numeric \\newcommand constants defined by the packaged libraries
    (\\grid = 1.6, \\sfgR, the sc_lib geometry, ...)."""
    from importlib import resources

    from ..render import lib_names

    consts: dict[str, str] = {}
    root = resources.files("cictikz") / "data" / "tex"
    for name in lib_names():
        consts.update(
            re.findall(r"\\newcommand\{\\(\w+)\}\{(-?[\d.]+)\}", (root / name).read_text())
        )
    return consts


class DialectError(ValueError):
    def __init__(self, msg: str, line: int):
        super().__init__(f"line {line}: {msg} (not cictikz dialect)")
        self.line = line


def _sanitize_net(label: str) -> str:
    """A TeX port label like $v_{o}$ becomes the net name v_o."""
    return re.sub(r"[${}\\\s]", "", label) or "net"


def read_tikz(text: str, registry: SymbolRegistry | None = None) -> Schematic:
    registry = registry or SymbolRegistry.load()
    sch = Schematic("figure")
    coords: dict[str, tuple[float, float]] = {}
    counter = {"port": 0, "inst": 0}

    # Strip comments, keep line structure for error messages.
    stripped = "\n".join(line.split("%", 1)[0] for line in text.splitlines())

    # Tolerate complete figure files: document scaffolding carries no
    # schematic content, so drop it rather than reject it.
    stripped = re.sub(
        r"\\input\{[^}]*\}|\\(begin|end)\{[^}]*\}(\[[^\]]*\])?|\\documentclass(\[[^\]]*\])?\{[^}]*\}",
        "",
        stripped,
    )

    # Numeric constants: the library's (\grid and friends) plus any the
    # figure defines locally (\newcommand{\xl}{2.4}) - substitute them so
    # coordinates like (\xl,0) or (0,\grid/4) become plain arithmetic.
    consts = dict(_lib_constants())
    #- Constant bodies may be expressions over earlier constants
    #  (\def\xr{\grid*2.5}); resolve iteratively until nothing new.
    defs = re.findall(r"\\(?:newcommand|def)\{?\\(\w+)\}?\{([-\d.*/+() \\\w]+)\}",
                      stripped)
    pending = [(n, b) for n, b in defs]
    for _ in range(4):
        still = []
        for n, body in pending:
            expr = re.sub(r"\\(\w+)",
                          lambda m: consts.get(m.group(1), m.group(0)), body)
            if re.fullmatch(r"[-\d.*/+() ]+", expr):
                try:
                    consts[n] = repr(eval(expr, {"__builtins__": {}}, {}))
                    continue
                except Exception:
                    pass
            still.append((n, body))
        if not still:
            break
        pending = still
    stripped = re.sub(r"\\(?:newcommand|def)\{?\\\w+\}?\{[-\d.*/+() \\\w]+\}",
                      "", stripped)
    stripped = re.sub(
        r"\\(" + "|".join(re.escape(c) for c in consts) + r")\b",
        lambda m: consts[m.group(1)],
        stripped,
    )

    _local_colours.clear()
    _local_colours.update(re.findall(r"\\definecolor\{(\w+)\}", text))

    covered = []
    for m in _STMT.finditer(stripped):
        covered.append((m.start(), m.end()))
        line = stripped.count("\n", 0, m.start()) + 1
        kind, body = m.group(1), m.group(2)
        if kind == "fill":
            _expect_junction(body, line)
            continue
        if kind == "node":
            _read_node_stmt(body, sch, line, coords)
            continue
        _read_path(kind, body, sch, coords, counter, registry, line, stripped, m.start(2))

    leftovers = _uncovered(stripped, covered)
    if leftovers:
        pos, snippet = leftovers
        raise DialectError(f"unrecognised content '{snippet}'",
                           stripped.count("\n", 0, pos) + 1)
    return sch


def _expect_junction(body: str, line: int):
    m = re.fullmatch(
        rf"\s*(?:\[(?P<opts>[^\]]*)\])?\s*\(\s*{_EXPR}\s*,\s*{_EXPR}\s*\)\s*circle\s*\(\s*[\d.]+\s*\)\s*",
        body,
    )
    if not m:
        raise DialectError(f"\\fill only draws junction dots, got '{body.strip()[:40]}'", line)
    _check_style(m.group("opts"), line, "fill")


_BJT = re.compile(r"\s*(pnp|npn)\s*(?:,|$)")

#- circuitikz BJT anchors, measured from the rendered node (probe
#  with \pgfpointanchor): npn collector up, pnp collector down.
_BJT_PINS = {
    "npn": {"C": (0.0, 0.77), "B": (-0.84, 0.0), "E": (0.0, -0.77)},
    "pnp": {"C": (0.0, -0.77), "B": (-0.84, 0.0), "E": (0.0, 0.77)},
}


def _read_node_stmt(body: str, sch: Schematic, line: int, coords=None):
    #- BJTs: the house has no bipolar macro, so \node[pnp]/[npn] is the
    #  house way to draw one - a component, not a label.
    bm = re.fullmatch(
        rf"\s*\[(?P<opts>[^\]]*)\]\s*(?:\((?P<name>[\w\[\]]+)\)\s*)?at\s*"
        rf"\(\s*(?P<x>{_EXPR})\s*,\s*(?P<y>{_EXPR})\s*\)\s*\{{\s*\}}\s*",
        body,
    )
    if bm and _BJT.match(bm.group("opts") or ""):
        opts = [o.strip() for o in bm.group("opts").split(",")]
        kind = opts[0]
        anchor = "center"
        for o in opts[1:]:
            if o.startswith("anchor="):
                anchor = o.removeprefix("anchor=")
            elif not _COSMETIC.fullmatch(o):
                raise DialectError(f"node option '{o}' outside dialect", line)
        pins = dict(_BJT_PINS[kind])
        off = pins.get(anchor, (0.0, 0.0))
        cx = _num(bm.group("x")) - off[0]
        cy = _num(bm.group("y")) - off[1]
        name = bm.group("name") or f"Q{line}"
        from ..schematic import Instance
        sch.add(Instance(name, kind, pos=(cx, cy), args=opts[1:]))
        if coords is not None:
            for pn, (px, py) in pins.items():
                coords[f"{name}.{pn}"] = (round(cx + px, 6), round(cy + py, 6))
            coords[f"{name}.center"] = (round(cx, 6), round(cy, 6))
        return

    m = re.fullmatch(
        rf"\s*(?:\[(?P<opts>[^\]]*)\])?\s*(?:\(\w+\)\s*)?at\s*\(\s*(?P<x>{_EXPR})\s*,\s*(?P<y>{_EXPR})\s*\)\s*\{{(?P<text>{_NEST})\}}\s*",
        body,
    )
    if not m:
        raise DialectError(f"\\node not understood: '{body.strip()[:40]}'", line)
    anchor = "center"
    for opt in _check_style(m.group("opts"), line, "node").split(","):
        opt = opt.strip()
        if opt.startswith("anchor="):
            anchor = opt.removeprefix("anchor=")
    sch.add(Label(m.group("text"), pos=(_num(m.group("x")), _num(m.group("y"))), anchor=anchor))


def _read_path(kind, body, sch, coords, counter, registry, line, text, offset):
    cursor = (0.0, 0.0)
    have_cursor = False
    annotation = False  # arrowed/dashed strokes never become wires
    wire: list[tuple[float, float]] = []
    pending = None  # connector seen, waiting for its target point

    def lineno(pos):
        return text.count("\n", 0, offset + pos) + 1

    def flush():
        nonlocal wire
        if len(wire) >= 2 and kind == "draw" and not annotation:
            sch.add(Wire(points=wire))
        wire = []

    def arrive(pt, connected):
        nonlocal cursor, have_cursor, pending
        pt = (round(pt[0], 6), round(pt[1], 6))  # kill float accumulation
        if isinstance(pending, tuple) and pending[0] == "elem":
            flush()
            counter["inst"] += 1
            sch.add(Instance(
                f"B{counter['inst']}", f"bipole:{pending[1].split(',', 1)[0].strip()}",
                pos=cursor, geom={"end": [pt[0], pt[1]], "opts": pending[1]},
            ))
            cursor = pt
            have_cursor = True
            pending = None
            return
        if connected:
            if not wire:
                wire.append(cursor)
            if pending == "|-":
                wire.append((cursor[0], pt[1]))
            elif pending == "-|":
                wire.append((pt[0], cursor[1]))
            wire.append(pt)
        else:
            flush()
        cursor = pt
        have_cursor = True
        pending = None

    i = 0
    while i < len(body):
        m = _TOKEN.match(body, i)
        if not m:
            rest = body[i:].strip()
            if not rest:
                break
            raise DialectError(f"unrecognised path content '{rest[:40]}'", lineno(i))
        i = m.end()
        if m.group("rel"):
            delta = (_num(m.group("rx")), _num(m.group("ry")))
            arrive((cursor[0] + delta[0], cursor[1] + delta[1]), pending is not None)
        elif m.group("abs"):
            arrive((_num(m.group("ax")), _num(m.group("ay"))), pending is not None)
        elif m.group("named"):
            ref = m.group("nref")
            if ref not in coords:
                raise DialectError(f"unknown coordinate '({ref})'", lineno(m.start()))
            arrive(coords[ref], pending is not None)
        elif m.group("coord"):
            coords[m.group("cname")] = cursor
        elif m.group("conn"):
            pending = m.group("conn")
        elif m.group("opts"):
            popts = _check_style(m.group("popts"), lineno(m.start()), "path")
            # Arrowed or dashed strokes are annotation, not circuitry
            # (house style: very thick/arrows = annotation) - their
            # segments must not become wires in the netlist.
            if re.search(r"(->|<-|dashed|dotted)", popts):
                annotation = True
        elif m.group("to"):
            opts = m.group("toopts")
            head = opts.split(",", 1)[0].strip()
            if head in _ELEMENT_BIPOLES:
                # an element the library has no macro for (current source,
                # inductor, ...): allowed as an element instance
                pending = ("elem", opts)
            else:
                for opt in opts.split(","):
                    if not _ALLOWED_TO.fullmatch(opt.strip()):
                        raise DialectError(
                            f"to[{opts}] uses a bipole outside the dialect",
                            lineno(m.start()),
                        )
                pending = "--"
        elif m.group("node"):
            sch.add(Label(m.group("ntext"), pos=cursor, anchor=_node_anchor(m.group("nopts"), lineno(m.start()))))
        elif m.group("circle"):
            pass  # junction dot inside a draw
        elif m.group("cycle"):
            if pending and wire:
                arrive(wire[0], True)  # close the polygon back to its start
        elif m.group("rect"):
            flush()  # a rectangle outline is a shape, not wiring
            pending = None
        elif m.group("macro"):
            name = m.group("mname")
            args, i = _macro_args(body, i)
            flush()
            pending = None
            if name in PORT_MACROS:
                counter["port"] += 1
                sch.add(Port(_sanitize_net(args[0] if args else ""),
                             pos=cursor, direction=PORT_MACROS[name]))
                exit_ = registry.get(name).exit if name in registry.names() else (0, 0)
            else:
                try:
                    sym = registry.get(name)
                except KeyError:
                    raise DialectError(
                        f"macro \\{name} is not in the symbol registry", lineno(m.start())
                    ) from None
                if len(args) != sym.nargs:
                    raise DialectError(
                        f"\\{name} takes {sym.nargs} argument(s), got {len(args)}",
                        lineno(m.start()),
                    )
                counter["inst"] += 1
                iname = args[0] if sym.nargs and args and args[0] else f"X{counter['inst']}"
                sch.add(Instance(iname, sym.name, pos=cursor, args=args))
                for p in sym.pins:
                    pt = (cursor[0] + p.grid_xy[0], cursor[1] + p.grid_xy[1])
                    coords[f"{iname}.{p.name}"] = pt  # circuitikz anchor style
                    coords[f"{iname}_{p.name}"] = pt  # gate coordinate style
                for cname, (ex, ey) in (sym.exports or {}).items():
                    coords[cname] = (round(cursor[0] + ex, 6), round(cursor[1] + ey, 6))
                # macro arguments that label a port (the lvnmos gate label)
                for argno, pin in (sym.arg_ports or {}).items():
                    label = args[int(argno) - 1] if len(args) >= int(argno) else ""
                    if label.strip():
                        pdef = next(p for p in sym.pins if p.name == pin)
                        sch.add(Port(
                            _sanitize_net(label),
                            pos=(cursor[0] + pdef.grid_xy[0], cursor[1] + pdef.grid_xy[1]),
                            direction="in",
                        ))
                exit_ = sym.exit
            cursor = (round(cursor[0] + exit_[0], 6), round(cursor[1] + exit_[1], 6))
            have_cursor = True
    flush()


def _macro_args(body: str, i: int) -> tuple[list[str], int]:
    args = []
    while True:
        m = re.match(rf"\s*\{{({_NEST})\}}", body[i:])
        if not m:
            return args, i
        args.append(m.group(1))
        i += m.end()


def _node_anchor(opts: str | None, line: int) -> str:
    for opt in (opts or "").split(","):
        opt = opt.strip()
        if opt.startswith("anchor="):
            return opt.removeprefix("anchor=")
    return "center"


def _uncovered(text: str, covered: list[tuple[int, int]]):
    """First non-whitespace content outside recognised statements."""
    pos = 0
    for start, end in sorted(covered):
        chunk = text[pos:start].strip()
        if chunk:
            return pos + text[pos:start].index(chunk[0]), chunk[:40]
        pos = end
    chunk = text[pos:].strip()
    if chunk:
        return pos + text[pos:].index(chunk[0]), chunk[:40]
    return None
