"""Reproducible pdflatex rendering for cictikz figures.

The render loop is the product: an AI assistant compiles a figure,
looks at the PNG, and iterates. Errors therefore come back as the
parsed ``!``-lines from the TeX log, not the whole log.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

# pdfTeX stamps /CreationDate; pinning it makes rebuilds byte-identical.
REPRODUCIBLE_ENV = {
    "SOURCE_DATE_EPOCH": "1700000000",
    "FORCE_SOURCE_DATE": "1",
}


@dataclass
class RenderResult:
    ok: bool
    pdf_path: Path | None
    log: str
    errors: list[str] = field(default_factory=list)


class ToolMissingError(RuntimeError):
    """A required external tool (pdflatex, pdftoppm, ...) is not on PATH."""


def _require(tool: str) -> str:
    path = shutil.which(tool)
    if path is None:
        raise ToolMissingError(
            f"'{tool}' not found on PATH - install a TeX/poppler toolchain to render"
        )
    return path


def _data_tex(name: str) -> str:
    return (resources.files("cictikz") / "data" / "tex" / name).read_text()


def lib_names() -> list[str]:
    """All packaged macro libraries, cictikz_lib (which defines \\grid) first."""
    root = resources.files("cictikz") / "data" / "tex"
    names = sorted(
        e.name
        for e in root.iterdir()
        if e.name.endswith(".tex") and e.name != "cictikz_preamble.tex"
    )
    names.remove("cictikz_lib.tex")
    return ["cictikz_lib.tex", *names]


def wrap_body(body: str) -> str:
    """Wrap a bare macro body in the packaged preamble + circuitikz environment.

    Every packaged library is inlined (not ``\\input``) so the wrapped
    source is a single self-contained file that compiles from any
    directory; macro names are unique across the libraries.
    """
    libs = "\n".join(_data_tex(n) for n in lib_names())
    return (
        _data_tex("cictikz_preamble.tex")
        + "\n\\begin{circuitikz}[american, thick, transform shape, circuit ee IEC]\n"
        + libs
        + "\n"
        + body
        + "\n\\end{circuitikz}\n\\end{document}\n"
    )


def _parse_errors(log: str) -> list[str]:
    """Pull the actionable lines out of a TeX log: each '! ...' error and
    the 'l.<n>' line that locates it."""
    errors = []
    lines = log.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("! "):
            errors.append(line)
            for follow in lines[i + 1 : i + 6]:
                if follow.startswith("l."):
                    errors.append(follow)
                    break
    return errors


def render_tex(
    tex_source: str,
    workdir: Path | None = None,
    jobname: str = "figure",
    cwd: Path | None = None,
) -> RenderResult:
    """Compile TeX source to PDF.

    ``workdir`` keeps the build files (default: a temp dir the caller
    should not rely on beyond the returned pdf_path). ``cwd`` is where
    pdflatex runs, for sources whose ``\\input`` paths are relative to a
    repo root.
    """
    pdflatex = _require("pdflatex")
    if workdir is None:
        # Derive the dir from the source: pdfTeX's /ID hashes the output
        # path, so a stable path (plus SOURCE_DATE_EPOCH) makes rebuilds
        # of identical source byte-identical.
        digest = hashlib.sha1(tex_source.encode()).hexdigest()[:12]
        workdir = Path(tempfile.gettempdir()) / f"cictikz_{digest}"
    workdir.mkdir(parents=True, exist_ok=True)
    texfile = workdir / f"{jobname}.tex"
    texfile.write_text(tex_source)

    env = dict(os.environ, **REPRODUCIBLE_ENV)
    proc = subprocess.run(
        [
            pdflatex,
            "-interaction=nonstopmode",
            "-halt-on-error",
            f"-output-directory={workdir}",
            str(texfile),
        ],
        cwd=cwd or workdir,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    logfile = workdir / f"{jobname}.log"
    log = logfile.read_text(errors="replace") if logfile.exists() else proc.stdout
    pdf = workdir / f"{jobname}.pdf"
    ok = proc.returncode == 0 and pdf.exists()
    return RenderResult(
        ok=ok,
        pdf_path=pdf if ok else None,
        log=log,
        errors=[] if ok else (_parse_errors(log) or [f"pdflatex exited {proc.returncode}"]),
    )


def render_file(path: Path, cwd: Path | None = None) -> RenderResult:
    """Compile an existing .tex file.

    If the file uses repo-relative ``\\input`` (aic2026 style,
    ``\\input{tikz/fig_header.tex}``), pass the repo root as ``cwd`` —
    or leave it None and the parent directory containing the first
    ``\\input`` target is searched for upwards from the file.
    """
    path = Path(path).resolve()
    source = path.read_text()
    if cwd is None:
        cwd = _guess_root(path, source)
    return render_tex(source, jobname=path.stem, cwd=cwd)


def _guess_root(path: Path, source: str) -> Path:
    """Walk up from the file until every relative \\input target exists."""
    import re

    targets = re.findall(r"\\input\{([^}]+)\}", source)
    for parent in [path.parent, *path.parents]:
        if all((parent / t).exists() for t in targets):
            return parent
    return path.parent


def pdf_to_svg(pdf: Path, out: Path | None = None) -> Path:
    pdf = Path(pdf)
    out = Path(out) if out else pdf.with_suffix(".svg")
    if shutil.which("pdf2svg"):
        subprocess.run(["pdf2svg", str(pdf), str(out)], check=True, timeout=60)
    elif shutil.which("dvisvgm"):
        subprocess.run(
            ["dvisvgm", "--pdf", "-o", str(out), str(pdf)],
            check=True,
            capture_output=True,
            timeout=60,
        )
    else:
        raise ToolMissingError("neither 'pdf2svg' nor 'dvisvgm' found on PATH")
    return out


def pdf_to_png(pdf: Path, dpi: int = 150) -> bytes:
    pdftoppm = _require("pdftoppm")
    with tempfile.TemporaryDirectory(prefix="cictikz_png_") as tmp:
        prefix = Path(tmp) / "page"
        subprocess.run(
            [pdftoppm, "-png", "-r", str(dpi), "-singlefile", str(pdf), str(prefix)],
            check=True,
            timeout=60,
        )
        return prefix.with_suffix(".png").read_bytes()
