"""A linter for schematic figures.

The complaints that come back from reading a drawn schematic are almost
always geometric, and almost always the same four:

  * a wire drawn on top of another wire, or drawn twice;
  * a wire that stops in mid air, connected to nothing;
  * a junction dot where only two wires meet, which is not a junction;
  * three wires meeting with no dot, so the reader cannot tell a
    crossing from a connection.

All four are decidable from the coordinates, so they should not need a
human to notice them. This module reads the figure source, recovers the
segments and dots the author actually drew, and reports the four.

It works on the source rather than on the rendered PDF on purpose. The
PDF contains every stroke circuitikz emits - the zigzag inside a
resistor, the bars of a ground symbol, the two triangles of an arrow
head - and those are full of legitimately dangling ends and legitimately
overlapping strokes. The source contains the wires, which is what the
checks are about.

Coordinates that come from a node - (M1.gate), (resEnd), (cicOtaS_out) -
have no position until TeX runs. They are kept as opaque anchors: two
paths that both touch the same anchor are connected, and an endpoint at
an anchor is never reported as dangling. That is enough to keep the
false positive rate low without resolving the geometry of every macro.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Two coordinates are the same point if they are within this, in grid
# units. The house grid is 1.6, wires land on tenths, so a hundredth is
# comfortably below anything intentional.
TOL = 0.02

# A segment shorter than this is a stub inside a symbol, not a wire.
MIN_LEN = 0.05

# Macros that terminate a path: a wire ending in one of these is
# finished, not dangling.
TERMINATORS = (
    "vground", "vsupply", "ground", "portIn", "portOut", "portmIn",
    "portmOut", "vdd", "vss", "rdacPort",
)

# Path options that put something visible on the end of the wire, which
# likewise means it is not left open.
OPEN_END_MARKERS = ("-o", "o-", "-*", "*-", "->", "<-", "-{", "}-", "ocirc", "circ")


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def close(self, other: "Point", tol: float = TOL) -> bool:
        return abs(self.x - other.x) <= tol and abs(self.y - other.y) <= tol


@dataclass
class Segment:
    a: Point | str          # a Point, or an anchor name
    b: Point | str
    line: int
    component: bool = False  # drawn with to[...]: a device sits on it
    raw: str = ""
    symbol: bool = False     # a stroke from inside an expanded symbol
    wide: bool = False       # a heavy supply rail
    mirrored: bool = False   # device symbol drawn with its gate to the other side
    synthetic: bool = False  # stands in for a symbol macro's two terminals


@dataclass
class Dot:
    at: Point | str
    line: int
    radius: float = 0.075


@dataclass
class Finding:
    rule: str
    line: int
    message: str

    def __str__(self) -> str:
        return f"{self.line}: [{self.rule}] {self.message}"


@dataclass
class Figure:
    segments: list[Segment] = field(default_factory=list)
    dots: list[Dot] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    macros: dict = field(default_factory=dict)
    consts: dict = field(default_factory=dict)
    # named coordinates: \coordinate (n) at (x,y), and "coordinate (n)"
    # planted mid-path. Resolving these is what keeps a wire chain that
    # runs through a symbol from breaking into unconnected pieces.
    named: dict = field(default_factory=dict)
    # drawn circles: current sources, port rings, bubbles. A wire end
    # that touches one of these is finished, not loose.
    blobs: list = field(default_factory=list)
    # numeric points that sit on a path which also touches something the
    # linter could not resolve, so their connection count is a lower
    # bound rather than the truth.
    uncertain: list = field(default_factory=list)
    nodes: list = field(default_factory=list)   # (Point, anchor, text, scale, line)


# --------------------------------------------------------------------
# reading the source
# --------------------------------------------------------------------

_COMMENT = re.compile(r"(?<!\\)%.*")
_DEF = re.compile(r"\\def\s*\\([A-Za-z]+)\s*\{([^{}]*)\}")
_NEWCMD = re.compile(r"\\newcommand\s*\{?\\([A-Za-z@]+)\}?\s*(?:\[(\d+)\])?\s*\{")


def _balanced(text: str, start: int) -> tuple[str, int]:
    """Read the brace group that starts at text[start] == '{'."""
    depth, i = 0, start
    while i < len(text):
        if text[i] == "{" and (i == 0 or text[i - 1] != "\\"):
            depth += 1
        elif text[i] == "}" and text[i - 1] != "\\":
            depth -= 1
            if depth == 0:
                return text[start + 1:i], i + 1
        i += 1
    return text[start + 1:], len(text)


def read_macros(text: str) -> dict[str, tuple[int, str]]:
    """\\newcommand definitions, as name -> (argument count, body).

    The house symbol macros are themselves paths - a resistor is a run
    of ++ moves - so the linter does not need a table of what each one
    does. Expanding the definition in place makes the wire chain come
    out right on its own.
    """
    macros: dict[str, tuple[int, str]] = {}
    for m in _NEWCMD.finditer(text):
        body, _ = _balanced(text, m.end() - 1)
        macros[m.group(1)] = (int(m.group(2) or 0), body)
    return macros


def expand(text: str, macros: dict[str, tuple[int, str]], depth: int = 6,
           fence: set[str] | None = None) -> str:
    """Replace macro calls with their bodies, arguments substituted.

    `fence` names the macros whose expansion is a symbol - the library
    ones. A macro defined in the figure itself is the author's own
    shorthand, and what it draws is the author's own wire or label, so
    it is not fenced and the checks apply to it.
    """
    for _ in range(depth):
        out, i, changed = "", 0, False
        while i < len(text):
            m = re.compile(r"\\([A-Za-z]+)").match(text, i)
            if not m or m.group(1) not in macros:
                out += text[i]
                i += 1
                continue
            nargs, body = macros[m.group(1)]
            j, args = m.end(), []
            ok = True
            for _ in range(nargs):
                while j < len(text) and text[j] in " \t\n":
                    j += 1
                if j >= len(text) or text[j] != "{":
                    ok = False
                    break
                arg, j = _balanced(text, j)
                args.append(arg)
            if not ok:
                out += text[i]
                i += 1
                continue
            for k, arg in enumerate(args, start=1):
                body = body.replace(f"#{k}", arg)
            # Fence the expansion so the path walker can tell strokes
            # that belong to a symbol from wires the author drew. The
            # bars of a ground and the zigzag of a resistor are not
            # wires, and must not be counted as junctions or reported
            # as loose ends.
            if fence is None or m.group(1) in fence:
                out += " @SYM{ " + body + " }SYM@ "
            else:
                out += " " + body + " "
            i = j
            changed = True
        text = out
        if not changed:
            break
    return text


def _strip_comments(text: str) -> list[str]:
    """Blank out comments but keep the line count, so findings can cite
    a line number that matches the file."""
    return [_COMMENT.sub("", line) for line in text.splitlines()]


_SIMPLE_NEWCMD = re.compile(r"\\newcommand\s*\{?\\([A-Za-z]+)\}?\s*\{([^{}]*)\}")


def _constants(lines: list[str]) -> dict[str, str]:
    """\\def'd numeric constants, resolved against each other."""
    consts: dict[str, str] = {}
    for line in lines:
        for name, value in _DEF.findall(line):
            consts[name] = value.strip()
        # \grid and friends are \newcommand with no arguments
        for name, value in _SIMPLE_NEWCMD.findall(line):
            if re.fullmatch(r"[-+*/(). \d\\A-Za-z]*", value.strip()):
                consts.setdefault(name, value.strip())
    # a constant may be written in terms of an earlier one
    for _ in range(4):
        for name, value in list(consts.items()):
            consts[name] = _substitute(value, consts)
    return consts


def _substitute(expr: str, consts: dict[str, str]) -> str:
    def repl(m):
        name = m.group(1)
        return f"({consts[name]})" if name in consts else m.group(0)
    return re.sub(r"\\([A-Za-z]+)", repl, expr)


def _number(expr: str, consts: dict[str, str]) -> float | None:
    """Evaluate a coordinate component, or None if it is not arithmetic."""
    e = _substitute(expr, consts).strip().strip("{}").strip()
    if not e or re.search(r"[\\A-Za-z]", e):
        return None
    if not re.fullmatch(r"[-+*/(). \d]+", e):
        return None
    try:
        return float(eval(e, {"__builtins__": {}}, {}))  # noqa: S307 - arithmetic only
    except Exception:
        return None


# A coordinate: (expr,expr) with optional ++ or + prefix.
_COORD = re.compile(r"(\+\+|\+)?\(\s*([^()]*?(?:\([^()]*\)[^()]*?)*)\s*\)")


def _parse_coord(body: str, consts: dict[str, str]) -> Point | str | None:
    """A coordinate body is either two arithmetic components or a node
    name we keep opaque."""
    if ":" in body and "," not in body:      # polar, e.g. (30:1.2)
        return "polar"
    parts = _split_top(body)
    if len(parts) != 2:
        return body.strip() or None          # a node name, kept as an anchor
    x, y = (_number(p, consts) for p in parts)
    if x is None or y is None:
        return body.strip()
    return Point(x, y)


def _split_top(body: str) -> list[str]:
    """Split on commas that are not inside braces or parens."""
    out, depth, cur = [], 0, ""
    for ch in body:
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    out.append(cur)
    return out


_STATEMENT = re.compile(r"\\(draw|fill|path|filldraw)\b(.*?);", re.S)
_SCOPED = re.compile(
    r"(?P<scope>\\begin\{scope\})\s*(?P<opts>\[[^\]]*\])?"
    r"|(?P<endscope>\\end\{scope\})"
    r"|\\(?P<kind>draw|fill|path|filldraw)\b(?P<body>.*?);", re.S)
_CIRCLE = re.compile(r"circle\s*(?:\[[^\]]*\]|\(([^)]*)\))")


_INPUT = re.compile(r"\\input\{([^}]+)\}")


def _libraries(text: str, base: Path | None) -> str:
    """The \\input'ed library sources, so the symbol macros can be
    expanded. Missing files are simply skipped - the linter degrades to
    treating that symbol as an opaque anchor."""
    if base is None:
        return ""
    out = []
    for rel in _INPUT.findall(text):
        # \input paths are written relative to the repository root, not
        # to the figure, so a figure in tikz/l13/ has to look upwards for
        # them. Without this the whole symbol library is missing for
        # every figure in a subdirectory, and its geometry comes out
        # wrong rather than merely unknown.
        found = None
        for root in [base, *base.parents][:6]:
            for cand in (root / rel, root / Path(rel).name):
                if cand.is_file():
                    found = cand
                    break
            if found:
                break
        if found:
            out.append(found.read_text())
    return "\n".join(out)


_SCOPE_MARK = re.compile(
    r"(?P<open>\\begin\{scope\})\s*(?P<opts>\[[^\]]*\])?"
    r"|(?P<close>\\end\{scope\})")


def _shift_by_line(text: str, consts: dict, line_of, nlines: int):
    """The accumulated scope shift in effect on each line."""
    table = [(0.0, 0.0)] * nlines
    stack = [(0.0, 0.0)]
    pos = 1
    for m in _SCOPE_MARK.finditer(text):
        line = line_of(m.start())
        for i in range(pos, min(line + 1, nlines)):
            table[i] = stack[-1]
        pos = min(line + 1, nlines)
        if m.group("open"):
            opts = m.group("opts") or ""
            dx = dy = 0.0
            sm = re.search(r"shift\s*=\s*\{?\(([^)]*)\)\}?", opts)
            if sm:
                parts = _split_top(sm.group(1))
                if len(parts) == 2:
                    dx = _number(parts[0], consts) or 0.0
                    dy = _number(parts[1], consts) or 0.0
            stack.append((stack[-1][0] + dx, stack[-1][1] + dy))
        elif len(stack) > 1:
            stack.pop()
    for i in range(pos, nlines):
        table[i] = stack[-1]
    return table


def _blank_definitions(text: str) -> str:
    """Blank out \\newcommand bodies, keeping newlines so line numbers
    survive. Their statements carry #1 placeholders and mean nothing
    until the macro is called."""
    out = list(text)
    for m in _NEWCMD.finditer(text):
        _, end = _balanced(text, m.end() - 1)
        for i in range(m.start(), end):
            if out[i] != "\n":
                out[i] = " "
    return "".join(out)


_FOREACH = re.compile(r"\\foreach\s+(?P<vars>\\[A-Za-z]+(?:\s*/\s*\\[A-Za-z]+)*)"
                      r"\s*(?:\[[^\]]*\])?\s*in\s*\{(?P<list>[^{}]*)\}\s*")


def _expand_range(items: list[str]) -> list[str]:
    """Turn 1,...,4 into 1,2,3,4. Anything else is left alone."""
    out: list[str] = []
    i = 0
    while i < len(items):
        if items[i].strip() == "..." and out and i + 1 < len(items):
            try:
                lo = float(out[-1])
                hi = float(items[i + 1])
                step = lo - float(out[-2]) if len(out) > 1 else 1.0
            except ValueError:
                out.append(items[i])
                i += 1
                continue
            v = lo + step
            while (step > 0 and v <= hi + 1e-9) or (step < 0 and v >= hi - 1e-9):
                out.append(f"{v:g}")
                v += step
            i += 2
            continue
        out.append(items[i])
        i += 1
    return out


def _expand_foreach(text: str, depth: int = 3) -> str:
    """Unroll \\foreach loops.

    Without this the wires a loop draws do not exist as far as the
    checks are concerned, and everything they connect to looks orphaned
    - a truth table's rules, a bus, a row of identical cells.
    """
    for _ in range(depth):
        m = _FOREACH.search(text)
        if not m:
            break
        brace = text.find("{", m.end() - 1)
        if brace == -1:
            break
        body, end = _balanced(text, brace)
        names = [v.strip() for v in m.group("vars").split("/")]
        rows = _expand_range([v.strip() for v in m.group("list").split(",")])
        pieces = []
        for row in rows:
            values = [v.strip() for v in row.split("/")]
            if len(values) < len(names):
                continue
            chunk = body
            for name, value in zip(names, values):
                # Longest names first: \ab must not be hit by \a.
                # A literal replacement: a loop value may itself contain
                # backslashes, which re.sub would read as escapes.
                chunk = re.sub(re.escape(name) + r"(?![A-Za-z])",
                               lambda _m, v=value: v, chunk)
            pieces.append(chunk)
        text = text[:m.start()] + " ".join(" ".join(p.split("\n")) for p in pieces) + text[end:]
    return text


def _expand_local_calls(lines: list[str], local: dict, consts: dict) -> str:
    """Expand the figure's own macros where they are called."""
    text = _expand_foreach(_blank_definitions("\n".join(lines)))
    # Constants are not path macros; leave them for the evaluator.
    callable_ = {k: v for k, v in local.items() if k not in consts}
    if not callable_:
        return text
    out = []
    for line in text.split("\n"):
        if any("\\" + name in line for name in callable_):
            # Flattened onto the one line: a macro body spans several,
            # and letting them through would shift every line number
            # after the call, so findings would cite the wrong place and
            # the scope table would be read at the wrong offset.
            line = " ".join(expand(line, callable_, fence=set()).split("\n"))
        out.append(line)
    return "\n".join(out)


def parse(text: str, base: Path | None = None) -> Figure:
    """Recover the wires and dots from figure source."""
    libs = _libraries(text, base)
    lines = _strip_comments(text)
    consts = _constants(_strip_comments(libs) + lines)
    lib_macros = read_macros(libs)
    macros = dict(lib_macros)
    macros.update(read_macros("\n".join(lines)))
    fence = set(lib_macros)
    # A constant is not a path macro; expanding it here would just get in
    # the way of the arithmetic evaluator.
    for name in list(macros):
        if name in consts:
            del macros[name]
    # A figure often defines its own shorthand for a repeated branch,
    # and that shorthand contains whole statements. Those statements are
    # only real once the macro is called, so blank the definitions and
    # expand the calls in place - line by line, so a finding still cites
    # the line the call is on.
    local = read_macros("\n".join(lines))
    joined = _expand_local_calls(lines, local, consts)
    fig = Figure()
    fig.macros = macros
    fig.consts = consts

    # Line numbers: map an offset in `joined` back to a 1-based line.
    # Offsets are measured in the expanded text, which is what every
    # scanner below actually searches. The line count is unchanged, so
    # the numbers still refer to the file the author edits.
    starts = [0]
    for line in joined.split("\n"):
        starts.append(starts[-1] + len(line) + 1)

    def line_of(offset: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            if starts[mid] <= offset:
                lo = mid + 1
            else:
                hi = mid
        return lo

    # Scopes move what is drawn inside them. Without following the
    # shift, a truth table drawn in a shifted scope lands on top of the
    # schematic and every wire looks like it overlaps something.
    # \coordinate (name) at (x,y) is resolved up front: a \fill that
    # names one may be written before the definition is reached.
    for m in re.finditer(r"\\coordinate\s*\(([^)]+)\)\s*at\s*", joined):
        cm = _COORD.match(joined, m.end())
        if cm:
            pt = _parse_coord(cm.group(2), consts)
            if isinstance(pt, Point):
                fig.named[m.group(1).strip()] = pt

    # The shift in effect on each line, so the node scan below can place
    # a label drawn inside a shifted scope where it is actually drawn.
    line_shift = _shift_by_line(joined, consts, line_of, len(lines) + 2)

    shift = [(0.0, 0.0)]
    poisoned = [False]
    for m in _SCOPED.finditer(joined):
        if m.group("scope"):
            opts = m.group("opts") or ""
            dx = dy = 0.0
            sm = re.search(r"shift\s*=\s*\{?\(([^)]*)\)\}?", opts)
            if sm:
                parts = _split_top(sm.group(1))
                if len(parts) == 2:
                    dx = _number(parts[0], consts) or 0.0
                    dy = _number(parts[1], consts) or 0.0
            for key, sign in (("xshift", "x"), ("yshift", "y")):
                km = re.search(key + r"\s*=\s*(-?[\d.]+)\s*cm", opts)
                if km:
                    if sign == "x":
                        dx += float(km.group(1))
                    else:
                        dy += float(km.group(1))
            hard = any(k in opts for k in ("rotate", "scale", "xslant", "yslant"))
            shift.append((shift[-1][0] + dx, shift[-1][1] + dy))
            poisoned.append(poisoned[-1] or hard)
            continue
        if m.group("endscope"):
            if len(shift) > 1:
                shift.pop()
                poisoned.pop()
            continue
        kind, body = m.group("kind"), m.group("body")
        lineno = line_of(m.start())
        if poisoned[-1]:
            fig.skipped.append(
                f"line {lineno}: inside a rotated or scaled scope, not analysed")
            continue
        offset = shift[-1]
        if "\\foreach" in body or "foreach" in body:
            fig.skipped.append(f"line {lineno}: foreach loop not analysed")
            continue
        if kind in ("fill", "filldraw") and _CIRCLE.search(body):
            _read_dot(body, lineno, consts, fig, offset)
            continue
        if kind == "fill":
            continue                      # a filled region, not a wire
        _read_path(expand(body, macros, fence=fence), lineno, consts, fig,
                   body, offset)

    # Node labels, for the text-over-wire check. Expanded a line at a
    # time so a label drawn by the figure's own shorthand - \dsize and
    # friends - is checked too, without losing the line number.
    # Scanned over the same text the statements came from: with the
    # macro definitions blanked, so a label inside a definition is not
    # counted alongside the label its expansion produces.
    for lineno, raw in enumerate(joined.split("\n"), start=1):
        if "\\node" not in raw and not any(
                "\\" + name in raw for name in macros):
            continue
        line = expand(raw, macros, fence=fence)
        dx, dy = line_shift[min(lineno, len(line_shift) - 1)]
        for m in _NODE.finditer(line):
            body, _ = _balanced(line, m.end() - 1)
            pt = _parse_coord(m.group("pos"), consts)
            if isinstance(pt, str) and pt in fig.named:
                pt = fig.named[pt]
            if isinstance(pt, Point):
                fig.nodes.append((Point(pt.x + dx, pt.y + dy),
                                  m.group("opts") or "", body, lineno))

    return fig


def _read_dot(body: str, lineno: int, consts, fig: Figure,
              offset: tuple[float, float] = (0.0, 0.0)) -> None:
    cm = _CIRCLE.search(body)
    radius = _number(cm.group(1) or "0.075", consts) or 0.075
    coords = [c for c in _COORD.finditer(body[: cm.start()])]
    if not coords:
        return
    pt = _parse_coord(coords[-1].group(2), consts)
    if isinstance(pt, str) and pt in fig.named:
        pt = fig.named[pt]
    if pt is None:
        return
    # A big filled circle is a blob in a drawing, not a junction dot.
    if radius <= 0.2:
        if isinstance(pt, Point):
            pt = Point(pt.x + offset[0], pt.y + offset[1])
        fig.dots.append(Dot(pt, lineno, radius))


def _read_path(body: str, lineno: int, consts, fig: Figure,
               original: str | None = None,
               offset: tuple[float, float] = (0.0, 0.0)) -> None:
    """Walk a path, emitting a segment per connector."""
    # Drop node/coordinate labels so their braces do not confuse the
    # coordinate scanner, but remember whether the path ends in a marker.
    # Terminator macros are detected on the unexpanded statement: once
    # \vground has been expanded into its bars, the name is gone.
    source = original if original is not None else body
    # A heavy rail reads as a rail: a device landing on one is plainly a
    # connection, so it does not need a dot to say so.
    wide = bool(re.search(r"line width\s*=\s*([12]\.?\d*)pt", source)) \
        or "ultra thick" in source
    mirrored = "mirror" in source or re.search(r"\\[a-z]*vm[np]mos", source) is not None
    marker = any(k in source for k in OPEN_END_MARKERS)
    terminated = any(t in source for t in TERMINATORS)
    # Inline nodes carry their position from the path, so they cannot be
    # thrown away like a stray brace group: they are the labels most
    # likely to end up sitting on a wire.
    inline: list[tuple[str, str]] = []

    def _keep(m):
        inline.append((m.group(1) or "", m.group(3)))
        return f" @NODE{len(inline) - 1}@ "

    stripped = re.sub(
        r"node\s*(\[[^\]]*\])?\s*(\([^()]*\))?\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}",
        _keep, body)
    # A path closed with "cycle" is an outline - a comparator triangle, a
    # box, a shaded region. Wires do not close on themselves.
    closed = "cycle" in stripped

    tokens = _tokenise(stripped, consts)
    cur: Point | str | None = None
    pending: str | None = None
    depth = 0
    sym_entry: list = []
    unresolved = False
    numeric_here: list[Point] = []
    for kind, value in tokens:
        if kind == "sym":
            if value > 0:
                sym_entry.append(cur)
            elif sym_entry:
                start = sym_entry.pop()
                # A resistor or a capacitor carries the wire through it;
                # without this the node at either end looks like it has
                # one connection fewer than it really has.
                if (isinstance(start, Point) and isinstance(cur, Point)
                        and not start.close(cur)):
                    fig.segments.append(Segment(start, cur, lineno,
                                                component=True,
                                                raw=source.strip()[:70],
                                                synthetic=True))
            depth += value
            continue
        if kind == "circle":
            if isinstance(cur, Point):
                fig.blobs.append((cur, value))
            continue
        if kind == "inline":
            opts, text = inline[value]
            if isinstance(cur, Point) and depth == 0 and text.strip():
                fig.nodes.append((cur, opts, text, lineno))
            continue
        if kind in ("coord", "rel"):
            if isinstance(value, str):
                unresolved = True
            elif isinstance(value, Point) and kind == "coord":
                numeric_here.append(value)
        if kind == "name":
            # "coordinate (n)" plants a name on the point we are standing
            # on, so a later (n) resolves instead of breaking the chain.
            if isinstance(cur, Point):
                fig.named[value] = cur
            continue
        if kind == "coord":
            pt = value
            if isinstance(pt, Point):
                pt = Point(pt.x + offset[0], pt.y + offset[1])
            elif isinstance(pt, str) and pt in fig.named:
                pt = fig.named[pt]
            if pending and cur is not None:
                _emit(fig, cur, pt, lineno, pending, source, depth > 0 or closed, wide, mirrored)
            cur = pt
            pending = None
        elif kind == "rel":
            if isinstance(cur, Point) and isinstance(value, Point):
                nxt = Point(cur.x + value.x, cur.y + value.y)
            else:
                nxt = value if isinstance(value, Point) else "relative"
            if pending and cur is not None:
                _emit(fig, cur, nxt, lineno, pending, source, depth > 0 or closed, wide, mirrored)
            cur = nxt
            pending = None
        elif kind == "conn":
            pending = value

    # A path that mentions a coordinate the linter cannot resolve - a
    # circuitikz node anchor like (M1.gate), or anything built with calc
    # - connects its numeric points to somewhere unknown. Record them so
    # the checks do not claim a junction is short of connections when
    # the missing one is simply invisible from here.
    if unresolved:
        fig.uncertain.extend(numeric_here)


def _emit(fig: Figure, a, b, lineno: int, conn: str, raw: str,
          symbol: bool = False, wide: bool = False,
          mirrored: bool = False) -> None:
    if a is None or b is None:
        return
    if isinstance(a, Point) and isinstance(b, Point):
        if abs(a.x - b.x) < MIN_LEN and abs(a.y - b.y) < MIN_LEN:
            return
    # to[short] is a wire with an option on it, not a device. Only a
    # real component gets pins and a symbol body.
    if conn.startswith("rectangle") and isinstance(a, Point) and isinstance(b, Point):
        # A box outline is not a wire, but a wire may legitimately stop
        # on one, so record the four edges as symbol strokes.
        corners = [Point(a.x, a.y), Point(b.x, a.y), Point(b.x, b.y), Point(a.x, b.y)]
        for k in range(4):
            fig.segments.append(Segment(corners[k], corners[(k + 1) % 4], lineno,
                                        raw=raw.strip()[:70], symbol=True))
        return
    component = conn.startswith("to") and "short" not in conn
    if conn.startswith("|-") and isinstance(a, Point) and isinstance(b, Point):
        mid = Point(b.x, a.y)
        fig.segments.append(Segment(a, mid, lineno, raw=raw.strip()[:70], symbol=symbol, wide=wide))
        fig.segments.append(Segment(mid, b, lineno, raw=raw.strip()[:70], symbol=symbol, wide=wide))
        return
    if conn.startswith("-|") and isinstance(a, Point) and isinstance(b, Point):
        mid = Point(a.x, b.y)
        fig.segments.append(Segment(a, mid, lineno, raw=raw.strip()[:70], symbol=symbol, wide=wide))
        fig.segments.append(Segment(mid, b, lineno, raw=raw.strip()[:70], symbol=symbol, wide=wide))
        return
    fig.segments.append(Segment(a, b, lineno, component, raw.strip()[:70], symbol, wide, mirrored))


_CONN = re.compile(r"--|\|-|-\||rectangle|to\s*(?:\[[^\]]*\])?")


_NAMED = re.compile(r"coordinate\s*\(\s*([^()]+?)\s*\)")
_SYMOPEN = re.compile(r"@SYM\{")
_SYMCLOSE = re.compile(r"\}SYM@")
_CIRC = re.compile(r"circle\s*\(\s*([^()]*)\s*\)")


def _tokenise(body: str, consts) -> list[tuple[str, object]]:
    out: list[tuple[str, object]] = []
    i = 0
    while i < len(body):
        m = _SYMOPEN.match(body, i)
        if m:
            out.append(("sym", 1))
            i = m.end()
            continue
        m = _SYMCLOSE.match(body, i)
        if m:
            out.append(("sym", -1))
            i = m.end()
            continue
        m = _CIRC.match(body, i)
        if m:
            out.append(("circle", _number(m.group(1), consts) or 0.1))
            i = m.end()
            continue
        m = re.compile(r"@NODE(\d+)@").match(body, i)
        if m:
            out.append(("inline", int(m.group(1))))
            i = m.end()
            continue
        m = _NAMED.match(body, i)
        if m:
            out.append(("name", m.group(1)))
            i = m.end()
            continue
        m = _COORD.match(body, i)
        if m:
            pt = _parse_coord(m.group(2), consts)
            out.append(("rel" if m.group(1) else "coord", pt))
            i = m.end()
            continue
        m = _CONN.match(body, i)
        if m:
            out.append(("conn", re.sub(r"\s+", "", m.group(0))))
            i = m.end()
            continue
        i += 1
    return out


# --------------------------------------------------------------------
# the checks
# --------------------------------------------------------------------

def _pts(seg: Segment) -> tuple[Point, Point] | None:
    if isinstance(seg.a, Point) and isinstance(seg.b, Point):
        return seg.a, seg.b
    return None


def _axis(seg: Segment) -> str | None:
    p = _pts(seg)
    if not p:
        return None
    a, b = p
    if abs(a.y - b.y) <= TOL:
        return "h"
    if abs(a.x - b.x) <= TOL:
        return "v"
    return None


def _on_segment(pt: Point, seg: Segment) -> bool:
    """Is pt strictly inside seg (not at either end)?"""
    p = _pts(seg)
    if not p:
        return False
    a, b = p
    ax = _axis(seg)
    if ax is None:
        # A slanted edge: the sloping side of an inverter or a
        # comparator, which wires do legitimately land on.
        dx, dy = b.x - a.x, b.y - a.y
        length = (dx * dx + dy * dy) ** 0.5
        if length < MIN_LEN:
            return False
        cross = abs((pt.x - a.x) * dy - (pt.y - a.y) * dx) / length
        if cross > 0.06:
            return False
        along = ((pt.x - a.x) * dx + (pt.y - a.y) * dy) / (length * length)
        return 0.02 < along < 0.98
    if ax == "h":
        if abs(pt.y - a.y) > TOL:
            return False
        lo, hi = sorted((a.x, b.x))
        return lo + TOL < pt.x < hi - TOL
    if ax == "v":
        if abs(pt.x - a.x) > TOL:
            return False
        lo, hi = sorted((a.y, b.y))
        return lo + TOL < pt.y < hi - TOL
    return False


def _overlap(s1: Segment, s2: Segment) -> float:
    """Length the two segments share, for collinear axis-aligned pairs."""
    if _axis(s1) != _axis(s2) or _axis(s1) is None:
        return 0.0
    a1, b1 = _pts(s1)
    a2, b2 = _pts(s2)
    if _axis(s1) == "h":
        if abs(a1.y - a2.y) > TOL:
            return 0.0
        lo1, hi1 = sorted((a1.x, b1.x))
        lo2, hi2 = sorted((a2.x, b2.x))
    else:
        if abs(a1.x - a2.x) > TOL:
            return 0.0
        lo1, hi1 = sorted((a1.y, b1.y))
        lo2, hi2 = sorted((a2.y, b2.y))
    return max(0.0, min(hi1, hi2) - max(lo1, lo2))


# A circuitikz transistor hangs its gate a little under a grid unit to
# the side of the channel, and its bulk the same the other way. A wire
# that lands there has landed on a pin, not in mid air.
PIN_REACH = 0.98


def _pins(fig: Figure) -> list[Point]:
    """Where a device can legitimately be connected: the two ends of the
    channel, and the gate and bulk out to either side of its middle."""
    out: list[Point] = []
    for seg in fig.segments:
        if not seg.component:
            continue
        p = _pts(seg)
        if not p:
            continue
        a, b = p
        out += [a, b]
        mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
        if _axis(seg) == "v":
            out += [Point(mx - PIN_REACH, my), Point(mx + PIN_REACH, my)]
        elif _axis(seg) == "h":
            out += [Point(mx, my - PIN_REACH), Point(mx, my + PIN_REACH)]
    return out


def _at_component(pt: Point, fig: Figure) -> bool:
    """Is pt on any device pin, channel ends included?"""
    return any(pt.close(q, 0.12) for q in _pins(fig))


def _at_side_pin(pt: Point, fig: Figure) -> bool:
    """Is pt on a gate or bulk pin - one that sticks out sideways and so
    has no segment of its own?

    The channel ends are excluded on purpose: a wire meeting one of them
    already contributes a direction through the device's own segment, and
    counting the pin as well would make every plain series connection
    look like a T.
    """
    for seg in fig.segments:
        if not seg.component:
            continue
        p = _pts(seg)
        if not p:
            continue
        a, b = p
        mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
        if _axis(seg) == "v":
            side = (Point(mx - PIN_REACH, my), Point(mx + PIN_REACH, my))
        elif _axis(seg) == "h":
            side = (Point(mx, my - PIN_REACH), Point(mx, my + PIN_REACH))
        else:
            continue
        if any(pt.close(q, 0.12) for q in side):
            return True
    return False


def _connections_at(pt: Point, fig: Figure) -> int:
    """The number of distinct directions conductor leaves pt in.

    Counting wire ends instead would make every corner look like a
    junction: two segments meet there, but it is one wire changing
    direction, and a dot on a corner means nothing. Directions are what
    distinguishes a corner (two) from a T (three).
    """
    dirs: set[tuple[int, int]] = set()
    for seg in fig.segments:
        if seg.symbol:
            continue
        p = _pts(seg)
        if not p:
            continue
        a, b = p
        if a.close(pt):
            dirs.add(_direction(a, b))
        if b.close(pt):
            dirs.add(_direction(b, a))
        # A synthetic segment stands in for a symbol whose real extent is
        # only approximately known, so only its terminals are trusted.
        if not seg.synthetic and _on_segment(pt, seg):
            dirs.add(_direction(pt, a))
            dirs.add(_direction(pt, b))
    return len(dirs)


def _direction(frm: Point, to: Point) -> tuple[int, int]:
    dx, dy = to.x - frm.x, to.y - frm.y
    n = max(abs(dx), abs(dy)) or 1.0
    return (round(dx / n), round(dy / n))


def check(fig: Figure) -> list[Finding]:
    out: list[Finding] = []

    # --- a wire drawn over another wire -----------------------------
    seen: set[tuple[int, int]] = set()
    wires = [s for s in fig.segments if not s.symbol]
    for i, s1 in enumerate(wires):
        for j, s2 in enumerate(wires[i + 1:], start=i + 1):
            if (i, j) in seen:
                continue
            shared = _overlap(s1, s2)
            if shared > 0.15:
                seen.add((i, j))
                out.append(Finding(
                    "overlapping-wire", s2.line,
                    f"{shared:.2f} units of this wire lie on top of the one "
                    f"drawn at line {s1.line}"))

    # --- junction dots ----------------------------------------------
    for dot in fig.dots:
        if not isinstance(dot.at, Point):
            continue
        if any(dot.at.close(u, 0.05) for u in fig.uncertain):
            continue
        # Same count the missing-dot check uses: a rail running past a
        # gate pin is a T even though only one wire passes through it.
        n = _connections_at(dot.at, fig) + (1 if _at_side_pin(dot.at, fig) else 0)
        if n and n < 3:
            out.append(Finding(
                "dot-without-junction", dot.line,
                f"junction dot at ({dot.at.x:g},{dot.at.y:g}) where wire runs "
                f"in only {n} direction{'s' if n != 1 else ''}, so nothing "
                f"joins there"))

    # --- a junction with no dot -------------------------------------
    dotted = [d.at for d in fig.dots if isinstance(d.at, Point)]
    candidates: dict[tuple[float, float], Point] = {}
    for seg in fig.segments:
        if seg.symbol:
            continue
        p = _pts(seg)
        if not p:
            continue
        for pt in p:
            candidates[(round(pt.x, 2), round(pt.y, 2))] = pt
    for pt in candidates.values():
        if any(pt.close(d) for d in dotted):
            continue
        n = _connections_at(pt, fig) + (1 if _at_side_pin(pt, fig) else 0)
        # Exactly three is a T, which is ambiguous without a dot. Four is
        # a crossing, and leaving it undotted is how a crossing is drawn.
        on_rail = any(
            s.wide and (_on_segment(pt, s)
                        or any(q.close(pt) for q in (_pts(s) or ())))
            for s in fig.segments)
        if n == 3 and not on_rail:
            out.append(Finding(
                "missing-junction-dot", _line_at(pt, fig),
                f"three or more wires meet at ({pt.x:g},{pt.y:g}) with no dot, "
                f"so a reader cannot tell it from a crossing"))

    # --- a wire that stops in mid air -------------------------------
    for seg in fig.segments:
        p = _pts(seg)
        if not p or seg.component or seg.symbol:
            continue
        # A rail carries its connections along its length, not at its
        # ends; its tip sticking out past the last one is deliberate.
        interior = any(
            _on_segment(q, seg)
            for other in fig.segments if not other.symbol and other is not seg
            for q in (_pts(other) or ()))
        if interior:
            continue
        # A wire that stops in mid air has one end attached to the
        # circuit and one end free. A stroke with BOTH ends free is not a
        # wire at all - it is a capacitor plate, an arrow, a tick, one
        # line of a hand-drawn symbol - and reporting those buries the
        # real ones.
        free = [q for q in p
                if _connections_at(q, fig) < 2
                and not any(q.close(d) for d in dotted)
                and not _terminated(q, seg, fig) and not _at_component(q, fig)]
        # Exactly one free end. A stroke free at BOTH ends is not a wire
        # that goes nowhere - it is a rule in a table, a capacitor plate,
        # a tick, one line of a hand-drawn symbol - and reporting those
        # buries the fault this rule exists to find.
        if len(free) != 1:
            continue
        for pt in p:
            if _connections_at(pt, fig) >= 2:
                continue
            if any(pt.close(d) for d in dotted):
                continue
            if any(pt.close(u, 0.05) for u in fig.uncertain):
                continue
            if _terminated(pt, seg, fig) or _at_component(pt, fig):
                continue
            out.append(Finding(
                "open-wire", seg.line,
                f"wire end at ({pt.x:g},{pt.y:g}) connects to nothing"))
    return out


def _line_at(pt: Point, fig: Figure) -> int:
    for seg in fig.segments:
        p = _pts(seg)
        if p and (p[0].close(pt) or p[1].close(pt)):
            return seg.line
    return 0


def _terminated(pt: Point, seg: Segment, fig: Figure) -> bool:
    """A loose end is fine when something was drawn on it: a ground, a
    supply, a port ring, an arrow head, a current source circle, or any
    stroke belonging to a symbol."""
    raw = seg.raw
    if any(t in raw for t in TERMINATORS) or any(k in raw for k in OPEN_END_MARKERS):
        return True
    for centre, radius in fig.blobs:
        if abs(pt.x - centre.x) <= radius + 0.1 and abs(pt.y - centre.y) <= radius + 0.1:
            return True
    for other in fig.segments:
        if not other.symbol:
            continue
        # A symbol's own strokes cannot vouch for the symbol's terminal:
        # a resistor whose lead ends in mid air ends in its own lead.
        if other.line == seg.line:
            continue
        q = _pts(other)
        if q and (q[0].close(pt, 0.1) or q[1].close(pt, 0.1)
                  or _on_segment(pt, other)):
            return True
    return False


RULES = (
    "overlapping-wire", "open-wire", "dot-without-junction",
    "missing-junction-dot", "duplicate-dot", "dot-on-component",
    "floating-terminal", "crowded-wires", "crowded-dots",
    "overlapping-labels", "text-over-device",
    "text-over-wire", "invisible-ground", "calc-syntax",
    "off-palette-colour",
)


def is_schematic(text: str) -> bool:
    """Is this a circuit, or a drawing?

    The wire checks only mean anything on a schematic. A band diagram or
    a timeline is built from strokes that are not wires, end where the
    author wanted them to end, and cross without connecting - running
    the topology rules over one produces nothing but noise.
    """
    return "\\begin{circuitikz}" in text


def lint_text(text: str, base: Path | None = None) -> tuple[list[Finding], Figure]:
    fig = parse(text, base)
    lib_colours = {c.lower() for c in re.findall(
        r"\\definecolor\{([^}]+)\}", _libraries(text, base))}
    findings = check_style(text, lib_colours) + check_text(fig)
    if is_schematic(text):
        findings += (check(fig) + check_dots_extra(fig) + check_crowding(fig)
                     + check_floating(fig) + check_labels(fig))
    order = {r: i for i, r in enumerate(RULES)}
    findings.sort(key=lambda f: (order.get(f.rule, 99), f.line))
    return findings, fig


def lint_file(path: str | Path) -> tuple[list[Finding], Figure]:
    path = Path(path)
    return lint_text(path.read_text(), path.parent)


# --------------------------------------------------------------------
# checks that are not about wires
#
# These come from mistakes that actually reached a rendered page: a
# label drawn across a wire, a ground that silently drew nothing, a
# colour that vanishes in a black and white print.
# --------------------------------------------------------------------

_NODE = re.compile(
    r"\\node\s*(?P<opts>\[[^\]]*\])?\s*(?:\([^()]*\))?\s*at\s*\(\s*(?P<pos>[^()]*(?:\([^()]*\)[^()]*)*)\s*\)\s*\{",
)

# The palette the book is drawn in. Everything here has a distinct
# luminance, so the figures survive a black and white print.
PALETTE = {
    "black", "white", "gray", "grey", "red", "blue", "armygreen", "orange",
    "oxteal", "echarge", "hcharge", "fieldy", "none",
}

# Average glyph width and line height as a fraction of the figure's
# unit, for the book's 10pt text at scale 1. Deliberately a little small
# so a near miss is not reported.
_CHAR_W = 0.17
_LINE_H = 0.38


def _text_box(pos, opts: str, text: str):
    """A rough rectangle for a node's text: (x0, y0, x1, y1)."""
    scale = 1.0
    m = re.search(r"scale\s*=\s*([\d.]+)", opts or "")
    if m:
        scale = float(m.group(1))
    lines = text.split(r"\\")
    plain = [re.sub(r"\\[A-Za-z]+|[${}^_]", "", ln).strip() for ln in lines]
    width = max((len(p) for p in plain), default=0) * _CHAR_W * scale
    height = len(lines) * _LINE_H * scale
    anchor = "center"
    m = re.search(r"anchor\s*=\s*([a-z ]+)", opts or "")
    if m:
        anchor = m.group(1).strip()
    x, y = pos.x, pos.y
    x0 = x - width / 2
    if "west" in anchor:
        x0 = x
    elif "east" in anchor:
        x0 = x - width
    y0 = y - height / 2
    if "south" in anchor:
        y0 = y
    elif "north" in anchor:
        y0 = y - height
    return (x0, y0, x0 + width, y0 + height)


def _box_hits_segment(box, seg: Segment) -> float:
    """How far a wire runs inside a text box, 0 if it misses."""
    p = _pts(seg)
    if not p:
        return 0.0
    a, b = p
    x0, y0, x1, y1 = box
    ax = _axis(seg)
    if ax == "h":
        if not (y0 < a.y < y1):
            return 0.0
        lo, hi = sorted((a.x, b.x))
        return max(0.0, min(hi, x1) - max(lo, x0))
    if ax == "v":
        if not (x0 < a.x < x1):
            return 0.0
        lo, hi = sorted((a.y, b.y))
        return max(0.0, min(hi, y1) - max(lo, y0))
    return 0.0


def _device_box(seg: Segment):
    """The rectangle a circuitikz device symbol covers.

    The symbol is not centred on the wire: the channel bar and the gate
    hang off to one side, and which side depends on whether the device
    was drawn mirrored. Placing a size label a fraction of a unit to the
    empty side is house style and perfectly readable; placing it on the
    body side buries the device under the text.
    """
    p = _pts(seg)
    if not p:
        return None
    a, b = p
    mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
    # Only a transistor is lopsided. A resistor or a capacitor is drawn
    # symmetrically about the wire, so a label just to one side of it is
    # clear of the symbol.
    if not re.search(r"[np]mos|mosfet|igfet", seg.raw or "", re.I):
        if _axis(seg) == "v":
            return (mx - 0.22, my - 0.5, mx + 0.22, my + 0.5)
        return (mx - 0.5, my - 0.22, mx + 0.5, my + 0.22)
    near, far = 0.15, 0.6
    if _axis(seg) == "v":
        lo, hi = (mx - near, mx + far) if seg.mirrored else (mx - far, mx + near)
        return (lo, my - 0.5, hi, my + 0.5)
    if _axis(seg) == "h":
        lo, hi = (my - near, my + far) if seg.mirrored else (my - far, my + near)
        return (mx - 0.5, lo, mx + 0.5, hi)
    return None


def _boxes_overlap(b1, b2) -> float:
    x = min(b1[2], b2[2]) - max(b1[0], b2[0])
    y = min(b1[3], b2[3]) - max(b1[1], b2[1])
    return min(x, y) if x > 0 and y > 0 else 0.0


def check_text(fig: Figure) -> list[Finding]:
    out = []
    for pos, opts, text, lineno in fig.nodes:
        if not isinstance(pos, Point) or not text.strip():
            continue
        box = _text_box(pos, opts, text)
        hit = False
        for seg in fig.segments:
            if not seg.component:
                continue
            dbox = _device_box(seg)
            if dbox and _boxes_overlap(box, dbox) > 0.10:
                label = re.sub(r"\s+", " ", text)[:28]
                out.append(Finding(
                    "text-over-device", lineno,
                    f'the label "{label}" is drawn over the device at line '
                    f"{seg.line}"))
                hit = True
                break
        if hit:
            continue
        for seg in fig.segments:
            if seg.symbol:
                continue
            run = _box_hits_segment(box, seg)
            if run > 0.12:
                label = re.sub(r"\s+", " ", text)[:28]
                out.append(Finding(
                    "text-over-wire", lineno,
                    f'the label "{label}" is drawn across the wire from '
                    f"line {seg.line} for about {run:.2f} units"))
                break
    return out


def check_style(text: str, extra_colours: set[str] | None = None) -> list[Finding]:
    """Things that are wrong before any geometry is considered."""
    out = []
    lines = _strip_comments(text)
    joined = "\n".join(lines)
    known = set(PALETTE) | set(extra_colours or ())
    # A colour the figure or its libraries define is a named colour with
    # a chosen luminance, not an ad hoc one.
    known |= {c.lower() for c in re.findall(r"\\definecolor\{([^}]+)\}", joined)}
    ee_scope = "circuit ee IEC" in joined
    for i, line in enumerate(lines, start=1):
        if not ee_scope and re.search(r"node\s*\[[^\]]*\bground\b", line):
            out.append(Finding(
                "invisible-ground", i,
                "node[ground] outside a 'circuit ee IEC' scope draws nothing "
                "at all - use \\vground"))
        if re.search(r"\(\s*\$.*\$\s*\)", line):
            out.append(Finding(
                "calc-syntax", i,
                "coordinate arithmetic with calc ($...$) is out of house "
                "style, and hides the geometry from this linter"))
        for colour in re.findall(r"(?:color|draw|fill)\s*=\s*([A-Za-z]+)", line):
            if colour.lower() not in known:
                out.append(Finding(
                    "off-palette-colour", i,
                    f"'{colour}' is not in the book palette, so it has no "
                    f"guaranteed luminance in a black and white print"))
        for colour in re.findall(r"\\draw\s*\[\s*([A-Za-z]+)[,\]]", line):
            if colour.lower() not in known and colour.lower() not in (
                    "thick", "very", "ultra", "thin", "dashed", "dotted",
                    "densely", "loosely", "->", "<-", "line", "rounded",
                    "american", "shift", "scale", "rotate", "step", "help"):
                out.append(Finding(
                    "off-palette-colour", i,
                    f"'{colour}' is not in the book palette, so it has no "
                    f"guaranteed luminance in a black and white print"))
    return out


def check_dots_extra(fig: Figure) -> list[Finding]:
    out = []
    seen: list[Point] = []
    for dot in fig.dots:
        if not isinstance(dot.at, Point):
            continue
        if any(dot.at.close(s) for s in seen):
            out.append(Finding(
                "duplicate-dot", dot.line,
                f"a junction dot was already drawn at "
                f"({dot.at.x:g},{dot.at.y:g})"))
        seen.append(dot.at)
        for seg in fig.segments:
            if seg.component and _in_body(dot.at, seg):
                out.append(Finding(
                    "dot-on-component", dot.line,
                    f"the dot at ({dot.at.x:g},{dot.at.y:g}) sits part way "
                    f"along the device drawn at line {seg.line}"))
                break
    return out


def _in_body(pt: Point, seg: Segment) -> bool:
    """Is pt inside the drawn symbol, rather than on the lead that runs
    from the symbol out to its terminal? A dot on a lead is an ordinary
    connection; a dot on the body is drawn over the device."""
    p = _pts(seg)
    if not p:
        return False
    a, b = p
    length = max(abs(a.x - b.x), abs(a.y - b.y))
    if length <= 0:
        return False
    if _axis(seg) == "v":
        t = (pt.y - a.y) / (b.y - a.y) if b.y != a.y else 0.5
        if abs(pt.x - a.x) > TOL:
            return False
    elif _axis(seg) == "h":
        t = (pt.x - a.x) / (b.x - a.x) if b.x != a.x else 0.5
        if abs(pt.y - a.y) > TOL:
            return False
    else:
        return False
    return 0.32 < t < 0.68


def check_floating(fig: Figure) -> list[Finding]:
    """A device with a terminal connected to nothing.

    The wire checks skip component segments, because a device is not a
    wire - which means an unconnected resistor or capacitor terminal was
    invisible to every other rule. It shows on the page as a lead
    sticking out past the junction with nothing on the end of it.
    """
    out = []
    dotted = [d.at for d in fig.dots if isinstance(d.at, Point)]
    for seg in fig.segments:
        if not seg.component:
            continue
        p = _pts(seg)
        if not p:
            continue
        for pt in p:
            if _connections_at(pt, fig) >= 2:
                continue
            if any(pt.close(d) for d in dotted):
                continue
            if any(pt.close(u, 0.05) for u in fig.uncertain):
                continue
            if _terminated(pt, seg, fig):
                continue
            out.append(Finding(
                "floating-terminal", seg.line,
                f"the device terminal at ({pt.x:g},{pt.y:g}) connects to "
                f"nothing, so its lead hangs past the junction"))
    return out


def check_labels(fig: Figure) -> list[Finding]:
    """Two labels printed on top of each other.

    Nothing else notices this: both are legal, both are where the author
    put them, and the collision only exists once they are typeset.
    """
    out = []
    boxes = [(_text_box(pos, opts, text), text, lineno)
             for pos, opts, text, lineno in fig.nodes
             if isinstance(pos, Point) and text.strip()]
    for i, (b1, t1, l1) in enumerate(boxes):
        for b2, t2, l2 in boxes[i + 1:]:
            if _boxes_overlap(b1, b2) > 0.1:
                out.append(Finding(
                    "overlapping-labels", l2,
                    f'"{re.sub(r"\s+", " ", t2)[:20]}" is printed on top of '
                    f'"{re.sub(r"\s+", " ", t1)[:20]}" from line {l1}'))
    return out


def check_crowding(fig: Figure) -> list[Finding]:
    """Two wires doing one wire's job, or two dots on one node.

    This is what "messy" turns out to mean nearly every time: a pair of
    parallel wires a fraction of a unit apart, each with its own dot,
    where the reader expects one node.
    """
    out = []
    wires = [s for s in fig.segments if not s.symbol and not s.component]
    for i, s1 in enumerate(wires):
        for s2 in wires[i + 1:]:
            ax = _axis(s1)
            if ax is None or ax != _axis(s2):
                continue
            a1, b1 = _pts(s1)
            a2, b2 = _pts(s2)
            if ax == "h":
                gap = abs(a1.y - a2.y)
                lo1, hi1 = sorted((a1.x, b1.x))
                lo2, hi2 = sorted((a2.x, b2.x))
            else:
                gap = abs(a1.x - a2.x)
                lo1, hi1 = sorted((a1.y, b1.y))
                lo2, hi2 = sorted((a2.y, b2.y))
            shared = min(hi1, hi2) - max(lo1, lo2)
            if TOL < gap < 0.3 and shared > 0.3:
                out.append(Finding(
                    "crowded-wires", s2.line,
                    f"runs parallel to the wire at line {s1.line}, "
                    f"{gap:.2f} units away for {shared:.2f} units - too "
                    f"close to read as two separate nodes"))
    pts = [d for d in fig.dots if isinstance(d.at, Point)]
    for i, d1 in enumerate(pts):
        for d2 in pts[i + 1:]:
            gap = max(abs(d1.at.x - d2.at.x), abs(d1.at.y - d2.at.y))
            if TOL < gap < 0.3:
                out.append(Finding(
                    "crowded-dots", d2.line,
                    f"a second junction dot {gap:.2f} units from the one at "
                    f"line {d1.line}: two dots where a reader expects one node"))
    return out


def extent(fig: Figure) -> tuple[float, float]:
    """Width and height of the drawn wires, in figure units. A figure
    much wider than about 20 units will be shrunk to illegibility by the
    book's column, which is worth knowing before it is typeset."""
    xs, ys = [], []
    for seg in fig.segments:
        p = _pts(seg)
        if p:
            xs += [p[0].x, p[1].x]
            ys += [p[0].y, p[1].y]
    if not xs:
        return (0.0, 0.0)
    return (max(xs) - min(xs), max(ys) - min(ys))
