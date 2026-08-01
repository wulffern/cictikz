import unittest

from cictikz.symbols import SymbolRegistry


class TestSymbols(unittest.TestCase):
    def setUp(self):
        self.reg = SymbolRegistry.load()

    def test_loads_the_mvp_set(self):
        names = self.reg.names()
        for expect in ["vnmos", "lvpmos", "vresistor", "vground", "cicOta", "cmStd"]:
            self.assertIn(expect, names)
        self.assertGreaterEqual(len(names), 20)

    def test_get_strips_backslash(self):
        self.assertEqual(self.reg.get("\\lvnmos").name, "lvnmos")

    def test_unknown_symbol_lists_known(self):
        with self.assertRaises(KeyError):
            self.reg.get("nosuch")

    def test_transistor_geometry(self):
        s = self.reg.get("vnmos")
        self.assertEqual(s.exit, (0, 1.6))
        pins = {p.name: p for p in s.pins}
        self.assertEqual(pins["drain"].grid_xy, (0, 1.6))
        self.assertEqual(pins["source"].grid_xy, (0, 0))
        self.assertEqual(pins["gate"].direction, "in")

    def test_search(self):
        hits = [s.name for s in self.reg.search("mirror")]
        self.assertIn("cmStd", hits)


if __name__ == "__main__":
    unittest.main()
