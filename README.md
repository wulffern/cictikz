# cictikz

AI-driven TikZ circuit schematics.

A standalone Python package that ships the full aic2026 TikZ macro
vocabulary as package data — `cictikz_lib` (the `ckt_lib` schematic
dialect, grid = 1.6, one transistor tall) plus the domain libraries
(`boot`, `constellation`, `dacsm`, `esd`, `gmc`, `mos`, `plane`,
`rdac`, `sc`, `sfg`, `spec`) — renders figures reproducibly with
`pdflatex`, and exposes the whole loop —
discover symbols, render, look at the result — to an AI assistant over
MCP. Later phases add a schematic IR with writers/readers for the
constrained TikZ dialect and xschem `.sch` files.

## Install

```sh
make dev-install        # pip install -e ".[mcp]"
```

Rendering needs `pdflatex` (with `standalone` + `circuitikz`) on PATH,
and `pdftoppm` (poppler) for PNG / `pdf2svg` for SVG. Without them the
package still imports; render calls fail with a clear message and the
render tests skip.

## CLI

```sh
cictikz render fig.tex --png        # compile a full standalone figure
cictikz render body.tex --wrap      # wrap a bare macro body in the packaged preamble
cictikz symbols [QUERY]             # list the symbol library
cictikz info vnmos                  # pins, entry/exit, example for one symbol
cictikz draw spec.json --fmt tikz   # schematic IR (JSON) -> TikZ or xschem
cictikz tikz2sch fig.tex            # dialect TikZ -> xschem .sch
cictikz sch2tikz circuit.sch        # any xschem .sch -> dialect TikZ
cictikz export-symlib DIR           # generate cictikz/*.sym for xschem
cictikz watch fig.tex               # live preview: recompile on save, browser follows
```

`watch` is the iteration loop: edit the file in any editor (or let an AI
edit it), and the browser shows the new render half a second later —
compile errors appear inline instead of a stale image.

The TikZ-to-xschem direction accepts only the cictikz dialect (registry
macros, moves, named coordinates, `--`/`|-`/`-|`/`to[short]` wires) and
fails loudly with a line number on anything else; xschem-to-TikZ works
on any `.sch`, drawing unrecognised symbols as labelled boxes.

## MCP

```sh
claude mcp add cictikz -- cictikz-mcp
```

Tools: `render_tikz` (source → PNG, or the parsed TeX errors),
`render_file`, `list_symbols`, `symbol_info`, `style_guide`,
`list_examples` / `get_example` (searches a figure corpus; set
`CICTIKZ_EXAMPLES` to a directory of `.tex` figures).

## Figure dialect

Figures are written against `cictikz_lib.tex` (macro names identical to
the aic2026 course repo's `ckt_lib.tex`): path-fragment macros that
compose in one `\draw`, e.g.

```latex
\draw (0,0) \vground \vresistor{$R_s$} \lvnmos{M1}{$v_i$};
\draw (M1.drain) to[short] ++(0,\grid);
```

See `cictikz style-guide` (or the MCP `style_guide` tool) for the house
rules: one line width, one arrow tip, colour only when it means
something.
