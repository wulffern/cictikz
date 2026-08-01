import unittest


class TestMcpSmoke(unittest.TestCase):
    def test_server_imports_and_registers_tools(self):
        try:
            from cictikz import mcp_server
        except ImportError:
            self.skipTest("mcp extra not installed")
        # Tool functions exist and are documented (the docstring is the
        # client-facing parameter documentation).
        for name in [
            "render_tikz",
            "render_file",
            "list_symbols",
            "symbol_info",
            "style_guide",
            "draw_schematic",
            "list_examples",
            "get_example",
        ]:
            fn = getattr(mcp_server, name)
            self.assertTrue(fn.__doc__, name)

    def test_list_symbols_without_tex(self):
        try:
            from cictikz import mcp_server
        except ImportError:
            self.skipTest("mcp extra not installed")
        out = mcp_server.list_symbols("resistor")
        self.assertIn("vresistor", out)


if __name__ == "__main__":
    unittest.main()
