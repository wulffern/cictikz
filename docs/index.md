# cictikz documentation

cictikz packages a circuit-schematic TikZ dialect — the `ckt_lib`
macro vocabulary from the [aic2026](https://github.com/wulffern/aic2026)
course, grid = 1.6, one transistor tall — together with everything an AI
assistant (or a human) needs to draw with it:

- a **[symbol library](symbols.md)** with machine-readable pin geometry
  (49 symbols, one YAML each, rendered gallery), plus
  **[eleven domain libraries](libraries.md)** (switched-cap, signal-flow,
  ESD, MOS cartoons, ...),
- a **reproducible renderer**: `pdflatex` with pinned
  `SOURCE_DATE_EPOCH` and a source-hashed work directory, so identical
  source rebuilds byte-identical PDFs,
- a **[CLI](cli.md)** for rendering, converting, and live preview,
- an **[MCP server](mcp.md)** exposing the draw–render–look loop,
- a schematic **IR with converters** to and from xschem —
  see [the dialect and converters](dialect.md).

## The five-minute version

```sh
pip install -e ".[mcp]"          # or: make dev-install

cat > amp.tex <<'EOF'
\draw (0,0) \vground \vresistor{$R_s$} \lvnmos{M1}{$v_i$};
\draw (M1.drain) \portOut{$v_o$};
EOF

cictikz render amp.tex --wrap --png   # compile, look at amp.png
cictikz watch amp.tex                 # or: live-reload preview in the browser
```

Macros are path fragments that compose inside one `\draw`: each starts
at the current point, draws itself, and leaves the cursor at its exit
point. Transistor instance names become circuitikz nodes, so
`(M1.drain)` is addressable afterwards. The house rules — one line
width, one arrow tip, colour only when it means something — ship with
the package: `cictikz style-guide`.

## Repository layout

```
src/cictikz/
  render.py            pdflatex/pdf2svg/pdftoppm wrappers, wrap_body
  symbols.py           SymbolRegistry over data/symbols/*.yaml
  schematic.py         the IR: Schematic/Instance/Wire/Port/Label, infer_nets
  writers/tikz.py      IR -> dialect TikZ
  writers/xschem.py    IR -> .sch (lab_pin connectivity, verified pin maps)
  writers/xschem_sym.py  .sym generation for cictikz-only symbols
  readers/tikz.py      dialect TikZ -> IR (rejects non-dialect loudly)
  readers/xschem.py    any .sch -> IR (aliases, .sym geometry, opaque blocks)
  watch.py             live-preview HTTP server
  mcp_server.py        FastMCP stdio server
  data/tex/            the packaged preamble + 12 macro libraries
  data/symbols/        one YAML per symbol (generated, see scripts/)
scripts/
  gen_symbols.py       regenerates data/symbols/*.yaml
  gen_symbol_docs.py   regenerates docs/symbols.md + docs/symbols/*.svg
```

Both `data/symbols/` and `docs/symbols*` are generated — edit the
scripts, not the outputs.
