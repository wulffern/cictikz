# JSSC 2016 compiled-SAR figures

The TikZ figure sources from *"A Compiled 9-bit 20-MS/s 3.5-fJ/conv.step
SAR ADC in 28-nm FDSOI for Bluetooth Low Energy Receivers"* (JSSC 2016),
copied from the paper's public repository. These drawings predate — and
fathered — the `ckt_lib` dialect this package packages: the same 1.6
grid, the same `to [Tnmos]` chains, the same wiring idioms.

Build any figure from inside `tex/`:

    cd tex && pdflatex fig_comparator.tex

`fig_*.tex` are standalone wrappers; `src_*.tex` are the circuit
bodies; `SAR_ESSCIRC16_28N.tex` is the generated per-design symbol
include; `lib/commands.tex` and `fig_header.tex` are the preamble.
Committed `.svg` previews sit next to each figure.

| figure | shows |
|---|---|
| fig_comparator | the dynamic comparator with dummies |
| fig_sar_logic | CDAC control, state logic and enable logic |
| fig_saremx | the SAR core schematic |
| fig_dmos / fig_dmos_json / fig_dmos_spreadshirt | the DMOS switch drawings |
| fig_io10msps | I/O timing at 10 MS/s |
| fig_timing | conversion timing diagram |
| fig_prior_art | prior-art architecture comparison |
| fig_process | process cross-section cartoon |
| fig_core_measurements | measured core waveforms |
| fig_cdac_state_control_transistors | CDAC state control at transistor level (from the 2015 working repo) |
| fig_sch_di | clock input: RC into the Schmitt IO inverter chain (2015 working repo) |
| fig_capacitors | the capacitor-array layout, metal by metal (2015 working repo) |
| fig_ciccreator | the compiler methodology flow (2015 working repo) |

Figures needing the paper's measurement data or die photographs
(toplevel, simulation, wideadcs, diephoto, methodology, table) are not
included — only what compiles self-contained.
