"""The linter has to catch the four wiring faults and stay quiet on a
figure that is drawn correctly. Both halves matter: a checker that cries
wolf on good figures gets switched off."""

from pathlib import Path

from cictikz.lint import lint_text

GOOD = r"""
\input{tikz/fig_header.tex}
\begin{circuitikz}[american, thick]
  \draw (0,0) -- (0,2);
  \draw (0,2) -- (3,2);
  \draw (3,2) -- (3,0);
  \draw (0,1) to [R] (3,1);
  \fill (0,1) circle (0.075);
  \fill (3,1) circle (0.075);
\end{circuitikz}
"""


def rules(text):
    findings, _ = lint_text(text)
    return sorted(f.rule for f in findings)


def test_clean_figure_is_quiet():
    assert rules(GOOD) == []


def test_overlapping_wire():
    bad = GOOD.replace(r"\draw (0,2) -- (3,2);",
                       "\\draw (0,2) -- (3,2);\n  \\draw (0,2) -- (2,2);")
    assert "overlapping-wire" in rules(bad)


def test_open_wire():
    # attached at one end, dangling at the other: the fault
    bad = GOOD.replace(r"\end{circuitikz}", "\\draw (3,2) -- (6,2);\n\\end{circuitikz}")
    assert "open-wire" in rules(bad)


def test_a_stroke_free_at_both_ends_is_not_a_wire():
    # a rule in a truth table, a capacitor plate, a tick
    fine = GOOD.replace(r"\end{circuitikz}", "\\draw (6,4) -- (8,4);\n\\end{circuitikz}")
    assert "open-wire" not in rules(fine)


def test_a_plot_is_not_a_schematic():
    # a staircase against a sine, drawn in a circuitikz environment for
    # the preamble: the strokes overlap on purpose
    plot = r"""\begin{circuitikz}
  \draw (0,0) -- (1,0) -- (1,1) -- (2,1);
  \draw (0,0) -- (1,0) -- (1,1) -- (2,1);
\end{circuitikz}"""
    assert "overlapping-wire" not in rules(plot)


def test_foreach_is_unrolled():
    # the wires a loop draws have to exist, or everything they touch
    # looks orphaned
    text = r"""\begin{circuitikz}
  \foreach \i in {1,2,3} { \draw (\i,0) -- (\i,2); }
  \draw (0,0) -- (4,0);
  \draw (0,2) -- (4,2);
\end{circuitikz}"""
    from cictikz.lint import parse
    assert len(parse(text).segments) == 5


def test_dot_without_junction():
    bad = GOOD.replace(r"\fill (0,1) circle (0.075);",
                       "\\fill (0,1) circle (0.075);\n  \\fill (0,2) circle (0.075);")
    assert "dot-without-junction" in rules(bad)


def test_missing_junction_dot():
    bad = GOOD.replace(r"\fill (0,1) circle (0.075);", "")
    assert "missing-junction-dot" in rules(bad)


def test_crowded_wires():
    bad = GOOD.replace(r"\draw (0,2) -- (3,2);",
                       "\\draw (0,2) -- (3,2);\n  \\draw (0,2.1) -- (3,2.1);")
    assert "crowded-wires" in rules(bad)


def test_invisible_ground_needs_the_ee_scope():
    bad = r"""\begin{tikzpicture}
  \draw (0,0) node[ground]{};
\end{tikzpicture}"""
    assert "invisible-ground" in rules(bad)


def test_drawings_skip_the_wire_checks():
    drawing = r"""\begin{tikzpicture}
  \draw (0,0) -- (2,0);
  \draw (4,4) -- (6,6);
\end{tikzpicture}"""
    assert "open-wire" not in rules(drawing)


def test_scope_shift_is_followed():
    # Without following the shift these two land on top of each other.
    text = r"""\begin{circuitikz}
  \draw (0,0) -- (2,0);
  \begin{scope}[shift={(0,-5)}]
    \draw (0,0) -- (2,0);
  \end{scope}
\end{circuitikz}"""
    assert "overlapping-wire" not in rules(text)
