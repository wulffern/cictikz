# MCP server

The point of cictikz is that an AI assistant can draw a schematic,
*look at it*, and iterate. The MCP server is that loop over stdio.

## Registration

```sh
pip install -e ".[mcp]"
claude mcp add cictikz -e CICTIKZ_EXAMPLES=$HOME/path/to/figures -- cictikz-mcp
```

`CICTIKZ_EXAMPLES` (optional) points at a directory of `.tex` figures —
for example a course repo's `tikz/` — and enables the example tools.

## Tools

| tool | what it does |
|---|---|
| `render_tikz(source, body_only=True, dpi=150)` | compile TikZ, return the PNG inline; on failure return the parsed TeX errors |
| `render_file(path, dpi=150)` | compile an existing figure file (repo-relative `\input` handled) |
| `list_symbols(query="")` | the symbol library, one line each |
| `symbol_info(name)` | signature, pin geometry, anchors, example |
| `style_guide()` | the packaged house rules |
| `draw_schematic(spec_json, fmt)` | build a circuit structurally from the IR (JSON), emit TikZ or xschem |
| `tikz_to_xschem(source)` | dialect TikZ body → `.sch` content, connectivity inferred from geometry |
| `xschem_to_tikz(path)` | any `.sch` → dialect TikZ body |
| `list_examples(query="")` | search the example corpus by filename and header comment |
| `get_example(name)` | full source of one example figure |

## The intended workflow

1. `style_guide()` once, so the drawing follows the house rules.
2. `list_examples("cascode")` — find an existing figure that looks like
   the one you are about to draw, `get_example` it, imitate its idioms.
3. `list_symbols()` / `symbol_info("lvnmos")` for macros and pin names.
4. Draw, then `render_tikz(...)` and **look at the image** — a clean
   compile says nothing about whether the drawing is right.
5. For structural work (netlists in, drawings out), build the IR as
   JSON and use `draw_schematic`; the docstring carries a complete
   spec example.

Heavy imports are deferred into the tool bodies, so the server starts
fast; rendered images travel as PNG bytes and temporary files are
cleaned up per call.
