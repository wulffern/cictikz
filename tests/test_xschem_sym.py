"""The symbol reader has to get the flip and the arcs right: xschem
counts y downwards, and TikZ starts an arc at the current point rather
than at the centre."""

import math

from cictikz.readers.xschem_sym import parse_sym, to_tikz

INV = """v {xschem version=3.0.0}
A 4 65 0 5 0 360 {}
L 4 20 -20 20 20 {}
L 4 20 20 60 0 {}
L 4 60 0 20 -20 {}
L 4 0 0 20 0 {}
B 5 -4 4 4 -4 {name=A dir=in pinnumber=1}
B 5 76 4 84 -4 {name=Y dir=out pinnumber=2}
"""


def test_y_is_flipped():
    sym = parse_sym(INV, scale=1.0)
    # (20,-20) in xschem is above the axis once flipped
    assert (20.0, 20.0, 20.0, -20.0) in sym.lines


def test_pins_are_named_and_placed():
    sym = parse_sym(INV, scale=1.0)
    assert sym.pins["A"] == (0.0, 0.0)
    assert sym.pins["Y"] == (80.0, 0.0)


def test_full_circle_becomes_a_circle():
    out = to_tikz(parse_sym(INV, scale=1.0), macro="t")
    assert "circle (5)" in out
    assert "arc" not in out


def test_partial_arc_starts_at_the_start_angle():
    sym = parse_sym("A 4 40 0 10 90 90 {}\n", scale=1.0)
    x, y, r, start, extent = sym.arcs[0]
    out = to_tikz(sym, macro="t")
    # the pen must be put at the start angle, not at (r,0)
    dx = r * math.cos(math.radians(start))
    dy = r * math.sin(math.radians(start))
    assert f"++({dx:.5g},{dy:.5g})" in out


def test_generated_macro_exports_pin_coordinates():
    out = to_tikz(parse_sym(INV, scale=1.0), macro="jnwInv")
    assert "\\newcommand{\\jnwInv}[1]{" in out
    assert "coordinate (#1_a)" in out
    assert "coordinate (#1_y)" in out
