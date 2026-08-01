# The dialect, the IR, and the xschem bridge

## The constrained TikZ dialect

Arbitrary TikZ cannot be parsed back into a circuit, so cictikz defines
a dialect and refuses everything outside it — loudly, with a line
number — rather than guessing. In dialect:

- `\draw` paths made of absolute `(x,y)` / relative `++(dx,dy)` moves,
  named coordinates (`coordinate (n)`, `(M1.drain)`, macro-exported
  names like `(resEnd)`), and registry macro invocations;
- wires as `--`, `|-`, `-|`, `to[short]` (any `*`/`o` decorations),
  plus `cycle` and `rectangle` for shapes;
- `\node` labels, `\fill ... circle` junction dots;
- numeric constants — `\grid`, library constants, figure-local
  `\newcommand{\xl}{2.4}` — and coordinate arithmetic (`\grid/4`,
  `{3.0+1.7}`), braced or bare;
- cosmetic style options (colours, dash patterns, line weights,
  anchors). Arrowed or dashed strokes are treated as *annotation* and
  never become wires, per the house style.

Out of dialect, deliberately: raw circuitikz bipoles (`to[R]`,
`to[cI]`), component node shapes (`node[pnp]`), the TikZ `calc`
library, pgfplots, and figure-local multi-argument macros.

## The IR

`cictikz.schematic` — plain dataclasses, JSON round-trip via
`to_dict`/`from_dict` (unknown keys rejected):

```json
{"name": "amp",
 "instances": [{"name": "M1", "symbol": "lvnmos", "pos": [0, 0],
                "args": ["M1", "$v_i$"],
                "conns": {"drain": "vo", "source": "vss", "gate": "vi"}}],
 "wires":  [{"points": [[0, 1.6], [0.8, 1.6]], "net": "vo"}],
 "ports":  [{"net": "vo", "pos": [0.8, 1.6], "direction": "out"}],
 "labels": [{"text": "$v_o$", "pos": [0.5, 2], "anchor": "west"}]}
```

Coordinates are figure units (`\grid` = 1.6), y up. `infer_nets()`
derives connectivity from geometry with a union–find over coincident
pins, wire endpoints and ports; ground/supply symbols name their whole
net; net names fall back to `net1, net2, ...`.

The round trip is exact: `write → read → infer_nets → write`
reproduces the TikZ byte for byte.

## The xschem bridge

Symbol metadata carries a **verified** xschem mapping — pin offsets
measured from the installed `.sym` files, rotation semantics
(`(x,y) → (-y,x)` per step, flip mirrors x first) checked against
xschem's own headless netlister:

- writes place instances at a per-symbol origin with default params and
  drop `devices/lab_pin.sym` markers exactly on the pin boxes —
  connectivity by label, no routing;
- ground/supply map to the `gnd.sym`/`vdd.sym` label symbols;
- horizontal passives are the vertical symbol with baked-in `rot=1`;
  mirrored transistor macros are baked-in `flip=1` — reads absorb the
  instance transform back into the right macro variant;
- wrapper transistors (`JNWTR_*`, `SUNTR_*`) are aliases with their own
  pin maps;
- unknown symbols stay opaque (`unknown:<path>`) and go back to xschem
  verbatim. With `read_sch(..., sym_dirs=[...])` their `.sym` geometry
  is resolved, and the TikZ writer draws a true-sized box with pins
  where the author put them — which preserves a hand-placed top-level
  floorplan. (For publication figures you will still want to redraw by
  hand at block-diagram weight; preserve the floorplan's *intent*, not
  its coordinates.)

Headless verification recipe:

```sh
cat > rc.tcl <<'EOF'
set XSCHEM_LIBRARY_PATH /path/to/xschem_library:/path/to/sky130
EOF
xschem --rcfile rc.tcl --netlist --quit --no_x -o out mysch.sch
```

(The library path must be set in the rc file; the environment variable
alone is not honoured.)
