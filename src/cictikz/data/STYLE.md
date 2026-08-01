# cictikz figure style guide

Condensed from the aic2026 course repo's `tikz/STYLE.md`. The point of
these rules is that a figure drawn today should sit next to one drawn
five years ago without either looking out of place.

## Environment

Every schematic figure lives in

```latex
\begin{circuitikz}[american, thick, transform shape, circuit ee IEC]
```

(or `tikzpicture[thick]` for non-circuit drawings), compiled against the
packaged preamble (`cictikz_preamble.tex`) with the packaged macro
library (`cictikz_lib.tex`) input inside the environment.

## Line width

One width for everything: the environment's `thick` (0.8 pt). Never set
`line width=` on wires or devices. The preamble sets
`\ctikzset{bipoles/thickness=1}` so circuitikz bipoles weigh the same as
the hand-rolled `\vresistor`. Heavier strokes (`very thick`) are for
**annotation only** — highlight arrows, "becomes" arrows — never
circuitry.

## Arrow tips

One filled tip everywhere: `Latex`, set globally as `\tikzset{>={Latex}}`.
A figure only ever writes `->`, `<-` or `<->`. Never `-latex`,
`-stealth` or `-{Triangle}`.

## Colour

Black is the default. Colour carries meaning, never decoration:

| colour | meaning |
|---|---|
| `red` | the thing the figure is about; danger; a bit value |
| `blue` / `mOne` | metal, signals, the combinational cloud |
| `armygreen` | equivalences, "becomes", derived quantities |
| `poly`, `active`, `cut`, `mOne`..`mFour` | layout layers |
| `echarge` / `hcharge` | electrons and holes in device cartoons |

If a figure would read the same in black, draw it in black.

## The symbol vocabulary

Use the macros in `cictikz_lib.tex` rather than re-inventing a
transistor: `\lvnmos{M1}{$v_i$}`, `\lvpmos`, `\lvmnmos`, `\lvmpmos`
(each spans `\grid` = 1.6 vertically), `\vground`, `\vsupply`,
`\vresistor`, `\vcapacitor`, `\vvsource`, `\portIn`, `\portOut`, the OTA
outlines (`\cicOta`), the current mirrors (`\cmStd`, `\cmCascode`).

Macros are path fragments: they start at the current point and compose
in a single `\draw`:

```latex
\draw (0,0) \vground \vresistor{$R_s$} \lvnmos{M1}{$v_i$};
\draw (M1.drain) to[short] ++(0,\grid);
```

Transistor instance names become circuitikz node names, so `(M1.gate)`,
`(M1.drain)`, `(M1.source)` are addressable after the macro.

## Wiring

Junction dots are `\fill (x,y) circle (0.075);`. Wires that cross
without a dot are **not** connected — never draw a hop.

The preamble does **not** load the TikZ `calc` library, so
`($(a)+(1,0)$)` fails — use named `\coordinate`s and `|-` / `-|`
instead. No `shapes.geometric` either (no `ellipse` node — use a
rounded rectangle). Avoid `\usetikzlibrary` inside a figure.

## Naming

Every macro name is prefixed (`\cic*`, `\boot*`, `\esd*`, ...). Short
generic names collide with LaTeX built-ins (`\th` is thorn) and the
redefinition is fatal, not a warning.

## Figure comments

Every figure starts with a comment saying what it shows and *why* it is
drawn the way it is. Reasons ("the sources cross, so both b0 devices
would hang off one tail") are worth more than descriptions ("four
transistors").

## Reviewing

A clean build says nothing about whether the drawing is right. Render
the result and look at it; when redrawing an original, compare point by
point: topology, every label, polarity, bubbles, arrow directions.
