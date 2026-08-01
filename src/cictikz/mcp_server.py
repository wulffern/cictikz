"""cictikz MCP server (stdio).

Register with a client, e.g.:

    claude mcp add cictikz -- cictikz-mcp

Tools: render_tikz (source -> PNG, or the parsed TeX errors),
render_file, list_symbols, symbol_info, style_guide, list_examples,
get_example. Set CICTIKZ_EXAMPLES to a directory of .tex figures (e.g.
the aic2026 repo's tikz/) to enable the example tools.
"""

from __future__ import annotations

import os
from pathlib import Path

# SDK >= 2.0 renamed FastMCP; support both (pattern from cicwave).
try:
    from mcp.server.mcpserver import Image, MCPServer as _Server  # type: ignore
except ImportError:
    from mcp.server.fastmcp import FastMCP as _Server, Image  # type: ignore

mcp = _Server(
    "cictikz",
    instructions=(
        "TikZ circuit schematic drawing in the cictikz/ckt_lib dialect. "
        "Workflow: style_guide() once, list_symbols()/symbol_info() to find "
        "macros, render_tikz() to compile a figure body and LOOK at the "
        "returned PNG before calling it done. list_examples()/get_example() "
        "find existing figures to imitate."
    ),
)


def _examples_dir() -> Path:
    d = os.environ.get("CICTIKZ_EXAMPLES", "")
    if not d:
        raise ValueError(
            "CICTIKZ_EXAMPLES is not set - point it at a directory of .tex figures"
        )
    p = Path(d).expanduser()
    if not p.is_dir():
        raise ValueError(f"CICTIKZ_EXAMPLES={d} is not a directory")
    return p


@mcp.tool()
def render_tikz(source: str, body_only: bool = True, dpi: int = 150):
    """Compile TikZ and return the rendered PNG (or compile errors as text).

    Args:
        source: TikZ source. With body_only=True (default) this is a bare
            figure body (\\draw commands using the cictikz macro dialect)
            that gets wrapped in the packaged preamble + symbol library.
            With body_only=False it must be a complete standalone document.
        body_only: whether to wrap source in the packaged preamble.
        dpi: PNG resolution.
    """
    from . import render as r

    tex = r.wrap_body(source) if body_only else source
    result = r.render_tex(tex)
    if not result.ok:
        return "compile failed:\n" + "\n".join(result.errors)
    return Image(data=r.pdf_to_png(result.pdf_path, dpi=dpi), format="png")


@mcp.tool()
def render_file(path: str, dpi: int = 150):
    """Compile an existing .tex figure file and return the rendered PNG.

    Handles repo-style figures whose \\input paths are relative to a repo
    root (the root is found by walking up until the \\input targets exist).

    Args:
        path: path to the .tex file.
        dpi: PNG resolution.
    """
    from . import render as r

    result = r.render_file(Path(path).expanduser())
    if not result.ok:
        return "compile failed:\n" + "\n".join(result.errors)
    return Image(data=r.pdf_to_png(result.pdf_path, dpi=dpi), format="png")


@mcp.tool()
def list_symbols(query: str = "") -> str:
    """List the cictikz symbol library: macro name + one-line description.

    Args:
        query: optional substring filter on name or description.
    """
    from .symbols import SymbolRegistry

    rows = SymbolRegistry.load().search(query)
    if not rows:
        return f"no symbols matching '{query}'"
    return "\n".join(f"{s.name:14s} {s.description}" for s in rows)


@mcp.tool()
def symbol_info(name: str) -> str:
    """Macro signature, pin geometry, node anchors and an example for one symbol.

    Args:
        name: symbol name from list_symbols, e.g. 'lvnmos'.
    """
    from .symbols import SymbolRegistry

    s = SymbolRegistry.load().get(name)
    lines = [
        s.signature(),
        s.description,
        f"entry {list(s.entry)}  exit {list(s.exit)}  (figure units, grid=1.6, y up)",
    ]
    lines += [f"pin {p.name:8s} at {list(p.grid_xy)}  [{p.direction}]" for p in s.pins]
    if s.nodes:
        lines.append("anchors: " + ", ".join(s.nodes))
    if s.example:
        lines.append("example:\n" + s.example)
    return "\n".join(lines)


@mcp.tool()
def draw_schematic(spec_json: str, fmt: str = "tikz"):
    """Build a circuit structurally from a JSON spec and return TikZ or xschem source.

    The spec is the cictikz schematic IR (coordinates in figure units,
    grid=1.6, y up):
      {"name": "amp",
       "instances": [{"name": "M1", "symbol": "lvnmos", "pos": [0, 0],
                      "args": ["M1", "$v_i$"],
                      "conns": {"drain": "vo", "source": "vss", "gate": "vi"}}],
       "wires":  [{"points": [[0, 1.6], [0, 2.4]], "net": "vo"}],
       "ports":  [{"net": "vo", "pos": [0, 2.4], "direction": "out"}],
       "labels": [{"text": "$v_o$", "pos": [0.5, 2], "anchor": "west"}]}
    Symbol names/pins come from list_symbols/symbol_info. With fmt="tikz"
    the result is a figure body you can pass to render_tikz to see it.

    Args:
        spec_json: the schematic IR as a JSON string.
        fmt: "tikz" (dialect figure body) or "xschem" (.sch file content).
    """
    import json

    from .schematic import Schematic
    from .writers.tikz import write_tikz
    from .writers.xschem import write_sch

    if fmt not in ("tikz", "xschem"):
        raise ValueError("fmt must be 'tikz' or 'xschem'")
    sch = Schematic.from_dict(json.loads(spec_json))
    return write_tikz(sch) if fmt == "tikz" else write_sch(sch)


@mcp.tool()
def style_guide() -> str:
    """The cictikz figure style guide (line widths, arrows, colour policy, wiring)."""
    from importlib import resources

    return (resources.files("cictikz") / "data" / "STYLE.md").read_text()


@mcp.tool()
def list_examples(query: str = "", limit: int = 40) -> str:
    """Search the example figure corpus (CICTIKZ_EXAMPLES) by filename and header comment.

    Args:
        query: substring matched against the file name and its leading comment lines.
        limit: maximum number of results.
    """
    root = _examples_dir()
    q = query.lower()
    rows = []
    for f in sorted(root.rglob("*.tex")):
        if "build" in f.parts:
            continue
        head = " ".join(
            line.lstrip("% ").strip()
            for line in f.read_text(errors="replace").splitlines()[:12]
            if line.lstrip().startswith("%")
        )
        if q in f.stem.lower() or q in head.lower():
            rows.append(f"{f.relative_to(root)}: {head[:120]}")
        if len(rows) >= limit:
            break
    return "\n".join(rows) or f"no examples matching '{query}'"


@mcp.tool()
def get_example(name: str) -> str:
    """Return the full TikZ source of one example figure.

    Args:
        name: path relative to CICTIKZ_EXAMPLES as reported by list_examples.
    """
    root = _examples_dir()
    f = (root / name).resolve()
    if root.resolve() not in f.parents and f != root.resolve():
        raise ValueError("path escapes the example corpus")
    if not f.exists():
        raise ValueError(f"no such example: {name}")
    return f.read_text()


def main():
    mcp.run()


if __name__ == "__main__":
    main()
