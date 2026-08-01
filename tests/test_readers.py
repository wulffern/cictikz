import unittest

from cictikz.readers.tikz import DialectError, read_tikz
from cictikz.readers.xschem import read_sch
from cictikz.schematic import Instance, Port, Schematic, Wire
from cictikz.symbols import SymbolRegistry
from cictikz.writers.tikz import write_tikz
from cictikz.writers.xschem import write_sch

REG = SymbolRegistry.load()


def amp() -> Schematic:
    sch = Schematic("amp")
    sch.add(Instance("GND", "vground", pos=(0, 0)))
    sch.add(Instance("M1", "lvnmos", pos=(0, 0), args=["M1", "$v_i$"],
                     conns={"source": "vss", "gate": "vi", "drain": "vo"}))
    sch.add(Instance("R1", "vresistor", pos=(0, 1.6), args=["$R_L$"],
                     conns={"minus": "vo", "plus": "vdd"}))
    sch.add(Wire(points=[(0, 1.6), (0.8, 1.6)], net="vo"))
    sch.add(Port("vo", pos=(0.8, 1.6), direction="out"))
    return sch


class TestTikzReader(unittest.TestCase):
    def test_reads_writer_output(self):
        body = write_tikz(amp(), REG)
        sch = read_tikz(body, REG)
        self.assertEqual({i.symbol for i in sch.instances},
                         {"vground", "lvnmos", "vresistor"})
        m1 = next(i for i in sch.instances if i.name == "M1")
        self.assertEqual(m1.args, ["M1", "$v_i$"])
        self.assertEqual(len(sch.ports), 1)
        self.assertEqual(sch.ports[0].net, "vo")
        self.assertEqual(sch.wires[0].points, [(0, 1.6), (0.8, 1.6)])

    def test_round_trip_tikz(self):
        # read -> infer_nets -> write reproduces the original byte for
        # byte, junction dots included (dots derive from connectivity).
        body = write_tikz(amp(), REG)
        sch = read_tikz(body, REG)
        sch.infer_nets(REG)
        self.assertEqual(body, write_tikz(sch, REG))

    def test_named_coordinates_and_anchors(self):
        sch = read_tikz(
            r"""\draw (0,0) coordinate (cS) \lvnmos{M1}{$v_i$};
                \draw (M1.drain) -- ++(0,0.8);
                \draw (cS) -- ++(1,0);""",
            REG,
        )
        self.assertEqual(sch.wires[0].points, [(0, 1.6), (0, 2.4)])
        self.assertEqual(sch.wires[1].points, [(0, 0), (1, 0)])

    def test_ortho_connectors(self):
        sch = read_tikz(r"\draw (0,0) |- (2,1);", REG)
        self.assertEqual(sch.wires[0].points, [(0, 0), (0, 1), (2, 1)])
        sch = read_tikz(r"\draw (0,0) -| (2,1);", REG)
        self.assertEqual(sch.wires[0].points, [(0, 0), (2, 0), (2, 1)])

    def test_to_short_is_a_wire(self):
        sch = read_tikz(r"\draw (0,0) to [short,-] ++(0,1) to [short,*-o] ++(1,0);", REG)
        self.assertEqual(sch.wires[0].points, [(0, 0), (0, 1), (1, 1)])

    def test_bipole_in_to_rejected(self):
        with self.assertRaises(DialectError):
            read_tikz(r"\draw (0,0) to [R=$R_1$] ++(0,2);", REG)

    def test_unknown_macro_rejected_with_line(self):
        with self.assertRaises(DialectError) as ctx:
            read_tikz("\\draw (0,0) -- (1,0);\n\\draw (0,0) \\myweird{x};", REG)
        self.assertEqual(ctx.exception.line, 2)

    def test_calc_syntax_rejected(self):
        with self.assertRaises(DialectError):
            read_tikz(r"\draw ($(a)+(1,0)$) -- (2,0);", REG)

    def test_infer_nets_joins_pin_wire_port(self):
        sch = read_tikz(
            r"""\draw (0,0) \vnmos{M1};
                \draw (0,1.6) -- (1,1.6);
                \draw (1,1.6) \portOut{$v_o$};""",
            REG,
        )
        sch.infer_nets(REG)
        m1 = sch.instances[0]
        self.assertEqual(m1.conns["drain"], "v_o")
        self.assertEqual(sch.wires[0].net, "v_o")


class TestXschemReader(unittest.TestCase):
    def test_round_trip_sch(self):
        text = write_sch(amp(), REG)
        sch = read_sch(text, REG)
        again = write_sch(sch, REG)
        # canonical after one pass: writing the re-read schematic is stable
        self.assertEqual(again, write_sch(read_sch(again, REG), REG))
        m1 = next(i for i in sch.instances if i.name == "M1")
        self.assertEqual(m1.symbol, "vnmos")  # canonical name for the shared .sym
        self.assertEqual(m1.conns["drain"], "vo")
        self.assertEqual(sch.ports[0].net, "vo")
        self.assertEqual(sch.ports[0].direction, "out")

    def test_unknown_symbol_kept_opaque_and_lossless(self):
        text = write_sch(amp(), REG) + "C {devices/res.sym} 200 -100 1 0 {name=R9}\n"
        sch = read_sch(text, REG)
        r9 = next(i for i in sch.instances if i.name == "R9")
        self.assertEqual(r9.symbol, "unknown:devices/res.sym")
        self.assertEqual(r9.rot, 1)
        self.assertIn("C {devices/res.sym} 200 -100 1 0 {name=R9}", write_sch(sch, REG))

    def test_unknown_symbol_becomes_labelled_box_in_tikz(self):
        sch = read_sch(
            "v {xschem version=3.0.0 file_version=1.2 }\n"
            "C {devices/res.sym} 40 -40 0 0 {name=R9}\n",
            REG,
        )
        out = write_tikz(sch, REG)
        self.assertIn("rectangle", out)
        self.assertIn("R9: res", out)

    def test_multiline_props_parse(self):
        text = (
            "v {xschem version=3.0.0 file_version=1.2 }\n"
            "K {type=subcircuit\nformat=\"@name @pinlist\"\n}\n"
            "C {devices/ipin.sym} 0 0 0 0 {name=p1\nlab=vin}\n"
        )
        sch = read_sch(text, REG)
        self.assertEqual(sch.ports[0].net, "vin")


if __name__ == "__main__":
    unittest.main()
