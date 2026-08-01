"""cictikz command line interface."""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.group()
@click.version_option(package_name="cictikz")
def main():
    """AI-driven TikZ circuit schematics."""


@main.command()
@click.argument("texfile", type=click.Path(exists=True, path_type=Path))
@click.option("--wrap", is_flag=True, help="Treat the file as a bare macro body and wrap it in the packaged preamble + library.")
@click.option("--svg", "want_svg", is_flag=True, help="Also produce SVG.")
@click.option("--png", "want_png", is_flag=True, help="Also produce PNG.")
@click.option("--dpi", default=150, show_default=True, help="PNG resolution.")
@click.option("-o", "--outdir", type=click.Path(path_type=Path), default=None, help="Output directory (default: next to the source).")
def render(texfile, wrap, want_svg, want_png, dpi, outdir):
    """Compile a figure to PDF (and optionally SVG/PNG)."""
    from . import render as r

    outdir = outdir or texfile.parent
    outdir.mkdir(parents=True, exist_ok=True)
    if wrap:
        result = r.render_tex(r.wrap_body(texfile.read_text()), jobname=texfile.stem)
    else:
        result = r.render_file(texfile)
    if not result.ok:
        click.echo("\n".join(result.errors) or "compile failed", err=True)
        sys.exit(1)
    pdf = outdir / f"{texfile.stem}.pdf"
    pdf.write_bytes(result.pdf_path.read_bytes())
    click.echo(f"wrote {pdf}")
    if want_svg:
        click.echo(f"wrote {r.pdf_to_svg(result.pdf_path, pdf.with_suffix('.svg'))}")
    if want_png:
        png = pdf.with_suffix(".png")
        png.write_bytes(r.pdf_to_png(result.pdf_path, dpi=dpi))
        click.echo(f"wrote {png}")


@main.command()
@click.argument("query", default="")
def symbols(query):
    """List the symbol library (optionally filtered by QUERY)."""
    from .symbols import SymbolRegistry

    for s in SymbolRegistry.load().search(query):
        click.echo(f"{s.name:14s} {s.description}")


@main.command()
@click.argument("name")
def info(name):
    """Show macro signature, pins and example for one symbol."""
    from .symbols import SymbolRegistry

    s = SymbolRegistry.load().get(name)
    click.echo(f"{s.signature()}\n  {s.description}")
    click.echo(f"  entry {list(s.entry)}  exit {list(s.exit)}  (figure units, grid=1.6)")
    for p in s.pins:
        click.echo(f"  pin {p.name:8s} at {list(p.grid_xy)}  [{p.direction}]")
    if s.nodes:
        click.echo(f"  anchors: {', '.join(s.nodes)}")
    if s.example:
        click.echo("  example:\n    " + s.example.replace("\n", "\n    "))


@main.command()
@click.argument("specfile", type=click.Path(exists=True, path_type=Path))
@click.option("--fmt", type=click.Choice(["tikz", "xschem"]), default="tikz", show_default=True)
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None, help="Output file (default: stdout).")
def draw(specfile, fmt, output):
    """Write a schematic JSON spec out as dialect TikZ or xschem .sch."""
    import json

    from .schematic import Schematic
    from .writers.tikz import write_tikz
    from .writers.xschem import write_sch

    sch = Schematic.from_dict(json.loads(specfile.read_text()))
    text = write_tikz(sch) if fmt == "tikz" else write_sch(sch)
    if output:
        output.write_text(text)
        click.echo(f"wrote {output}")
    else:
        click.echo(text, nl=False)


@main.command()
@click.argument("texfile", type=click.Path(exists=True, path_type=Path))
@click.option("--port", default=8317, show_default=True)
@click.option("--no-browser", is_flag=True, help="Don't open the browser automatically.")
def watch(texfile, port, no_browser):
    """Live preview: recompile TEXFILE on every save, auto-refresh in the browser."""
    from .watch import serve

    serve(texfile, port=port, open_browser=not no_browser)


@main.command("tikz2sch")
@click.argument("texfile", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
def tikz2sch(texfile, output):
    """Convert a dialect TikZ figure body to an xschem .sch."""
    from .readers.tikz import read_tikz
    from .symbols import SymbolRegistry
    from .writers.xschem import write_sch

    registry = SymbolRegistry.load()
    sch = read_tikz(texfile.read_text(), registry)
    sch.name = texfile.stem
    sch.infer_nets(registry)
    text = write_sch(sch, registry)
    output = output or texfile.with_suffix(".sch")
    output.write_text(text)
    click.echo(f"wrote {output}")


@main.command("sch2tikz")
@click.argument("schfile", type=click.Path(exists=True, path_type=Path))
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None)
def sch2tikz(schfile, output):
    """Convert an xschem .sch to a dialect TikZ figure body."""
    from .readers.xschem import read_sch
    from .symbols import SymbolRegistry
    from .writers.tikz import write_tikz

    registry = SymbolRegistry.load()
    text = write_tikz(read_sch(schfile, registry), registry)
    output = output or schfile.with_suffix(".tex")
    output.write_text(text)
    click.echo(f"wrote {output}")


@main.command("export-symlib")
@click.argument("outdir", type=click.Path(path_type=Path))
def export_symlib(outdir):
    """Generate xschem .sym files for cictikz-only symbols into OUTDIR/cictikz/."""
    from .writers.xschem_sym import export_symlib as export

    for path in export(outdir):
        click.echo(f"wrote {path}")


@main.command("style-guide")
def style_guide():
    """Print the figure style guide."""
    from importlib import resources

    click.echo((resources.files("cictikz") / "data" / "STYLE.md").read_text())


if __name__ == "__main__":
    main()
