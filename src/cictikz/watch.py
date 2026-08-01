"""Live figure preview: watch a .tex file, recompile on every save, and
serve an auto-refreshing page to the browser.

This is the rapid-iteration loop: the human (or an AI) edits the file in
any editor, the browser shows the new render half a second later, and
compile errors appear inline instead of a stale image. Deliberately not
a GUI editor - the .tex file stays the single source of truth, so
hand-edits, git, and AI edits all use the same channel.

Stdlib only: http.server + a polling mtime watcher.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PAGE = """<!doctype html>
<meta charset="utf-8">
<title>cictikz: %(name)s</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 1.5rem; background: #fff; }
  img { max-width: 100%%; border: 1px solid #ddd; padding: 1rem; background: #fff; }
  pre { background: #fee; border: 1px solid #e99; padding: 1rem; white-space: pre-wrap; }
  .meta { color: #666; font-size: 0.85rem; margin-bottom: 0.75rem; }
</style>
<div class="meta">%(path)s &mdash; recompiles on save; this page follows along.</div>
<div id="out"></div>
<script>
let v = -1;
async function tick() {
  try {
    const s = await (await fetch('/state')).json();
    if (s.version !== v) {
      v = s.version;
      const out = document.getElementById('out');
      out.innerHTML = s.ok
        ? '<img src="/fig.svg?v=' + v + '">'
        : '<pre>' + s.errors.replace(/</g, '&lt;') + '</pre>';
      document.title = (s.ok ? '' : '\\u274c ') + 'cictikz: %(name)s';
    }
  } catch (e) {}
  setTimeout(tick, 500);
}
tick();
</script>
"""


class _State:
    def __init__(self):
        self.version = 0
        self.ok = False
        self.errors = "compiling..."
        self.svg: bytes = b""
        self.lock = threading.Lock()


def _compile(path: Path, state: _State):
    from . import render as r

    source = path.read_text()
    if "\\documentclass" not in source:
        source = r.wrap_body(source)
    result = r.render_tex(source, jobname=path.stem)
    with state.lock:
        state.version += 1
        state.ok = result.ok
        if result.ok:
            try:
                state.svg = r.pdf_to_svg(result.pdf_path).read_bytes()
            except Exception as e:  # svg tool missing: fall back to error text
                state.ok = False
                state.errors = str(e)
        else:
            state.errors = "\n".join(result.errors)


def _watcher(path: Path, state: _State, interval: float = 0.4):
    last = None
    while True:
        try:
            mtime = path.stat().st_mtime_ns
        except FileNotFoundError:
            mtime = None
        if mtime != last:
            last = mtime
            if mtime is not None:
                try:
                    _compile(path, state)
                except Exception as e:
                    with state.lock:
                        state.version += 1
                        state.ok = False
                        state.errors = f"internal error: {e}"
        time.sleep(interval)


def serve(path: Path, port: int = 8317, open_browser: bool = True):
    path = Path(path).resolve()
    state = _State()
    threading.Thread(target=_watcher, args=(path, state), daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, ctype, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            with state.lock:
                if self.path.startswith("/state"):
                    body = json.dumps(
                        {"version": state.version, "ok": state.ok,
                         "errors": state.errors}
                    ).encode()
                    self._send(200, "application/json", body)
                elif self.path.startswith("/fig.svg"):
                    self._send(200, "image/svg+xml", state.svg)
                else:
                    page = PAGE % {"name": path.name, "path": str(path)}
                    self._send(200, "text/html", page.encode())

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"cictikz watch: {path}")
    print(f"cictikz watch: serving {url}  (Ctrl-C to stop)")
    if open_browser:
        import webbrowser

        threading.Thread(target=lambda: (time.sleep(0.3), webbrowser.open(url)),
                         daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
