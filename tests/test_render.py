import shutil
import unittest

from cictikz import render as r

HAVE_TEX = shutil.which("pdflatex") is not None
HAVE_PPM = shutil.which("pdftoppm") is not None

BODY = r"\draw (0,0) \vground \vresistor{$R_s$} \lvnmos{M1}{$v_i$};"


class TestWrap(unittest.TestCase):
    def test_wrap_is_self_contained(self):
        tex = r.wrap_body(BODY)
        self.assertIn(r"\documentclass", tex)
        self.assertIn(r"\begin{circuitikz}", tex)
        self.assertIn(r"\newcommand{\vresistor}", tex)
        self.assertNotIn(r"\input{", tex)
        self.assertTrue(tex.rstrip().endswith(r"\end{document}"))


@unittest.skipUnless(HAVE_TEX, "pdflatex not on PATH")
class TestRender(unittest.TestCase):
    def test_body_renders(self):
        result = r.render_tex(r.wrap_body(BODY))
        self.assertTrue(result.ok, msg="\n".join(result.errors))
        self.assertTrue(result.pdf_path.exists())

    def test_reproducible(self):
        a = r.render_tex(r.wrap_body(BODY))
        b = r.render_tex(r.wrap_body(BODY))
        self.assertEqual(a.pdf_path.read_bytes(), b.pdf_path.read_bytes())

    def test_error_reporting(self):
        result = r.render_tex(r.wrap_body(r"\draw (0,0) \nosuchmacro;"))
        self.assertFalse(result.ok)
        self.assertTrue(any("nosuchmacro" in e or e.startswith("! ") for e in result.errors))

    @unittest.skipUnless(HAVE_PPM, "pdftoppm not on PATH")
    def test_png(self):
        result = r.render_tex(r.wrap_body(BODY))
        png = r.pdf_to_png(result.pdf_path)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
