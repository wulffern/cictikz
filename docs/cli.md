# CLI

All commands live under one entry point, `cictikz`.

## Rendering

```sh
cictikz render fig.tex               # full standalone document -> fig.pdf
cictikz render body.tex --wrap       # bare macro body: wrapped in the
                                     # packaged preamble + all libraries
cictikz render fig.tex --svg --png --dpi 200 -o outdir/
```

Rendering is reproducible: `SOURCE_DATE_EPOCH` is pinned and the build
directory is derived from a hash of the source, so unchanged source
rebuilds byte-identical PDFs. Compile errors come back as the parsed
`!`-lines from the TeX log, not the whole log.

`render` on a repo-style figure (one that does
`\input{tikz/fig_header.tex}`) finds the repo root automatically by
walking up until every `\input` target exists.

## Live preview

```sh
cictikz watch fig.tex [--port 8317] [--no-browser]
```

Watches the file, recompiles on every save (about half a second), and
serves an auto-refreshing page. Compile errors appear inline in the
page instead of a stale image. This is the iteration loop: any editor —
or an AI editing the file — triggers the refresh, and the `.tex` file
stays the single source of truth.

## Symbols

```sh
cictikz symbols [QUERY]     # list the library, optionally filtered
cictikz info lvnmos         # signature, pins, anchors, example
cictikz style-guide         # the house rules
```

See the rendered [symbol gallery](symbols.md).

## Schematic IR and converters

```sh
cictikz draw spec.json --fmt tikz|xschem    # IR (JSON) -> source
cictikz tikz2sch fig.tex [-o out.sch]       # dialect TikZ -> xschem
cictikz sch2tikz circuit.sch [-o out.tex]   # any xschem -> dialect TikZ
cictikz export-symlib DIR                   # .sym files for cictikz-only symbols
```

`tikz2sch` accepts complete figure files (document scaffolding is
stripped) and infers connectivity from geometry: coincident pins, wire
endpoints and ports become one net; ground and supply symbols name
their whole net GND/VDD. The result netlists correctly in xschem — the
converted aic2026 NAND figure netlists as `.subckt nand B A Y`.

`sch2tikz` works on any schematic: recognised symbols (including the
sky130 fets and the JNWTR/SUNTR wrapper transistors) map to dialect
macros, with xschem rotation/flip absorbed into the mirrored macro
variants; unknown symbols are drawn as labelled boxes and survive a
round trip back to xschem verbatim.
