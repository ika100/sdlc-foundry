"""The console's HTTP server (spec 122, design.md "Console HTTP").

  make_server(repo_dir, sources, *, port=0) -> ThreadingHTTPServer   bound to 127.0.0.1 only

Every request is refused with 421 unless `Host` is `127.0.0.1:<port>`; every POST needs the per-start `X-Console-Token`.
Errors are JSON `{"error", "detail"}`. Static files are the two known files of `console/static/`.

Views are named in the route tables as `"module:function"` and imported on first use. A view gets the context `ctx`:

  ctx.repo_dir, ctx.sources, ctx.token, ctx.snapshot(repo=None), ctx.state(), ctx.source(name), ctx.data(name)

  page views     fn(ctx, query: dict[str, str]) -> full HTML (use `layout.page(..., state=ctx.state())`)
  panel views    fn(ctx, ident: str) -> HTML fragment; raise LookupError for an unknown id (404)
  palette        fragment(ctx, q: str) -> HTML fragment;  ask(ctx, question: str) -> dict

A view module that is not there yet gives a placeholder page (pages) or a 501 (fragments), never a crash."""
from __future__ import annotations

import json
import re
import secrets
import shlex
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from console import actions, handoff, layout, preview, sources as sources_mod
from console.html import esc

STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {"console.css": "text/css; charset=utf-8", "console.js": "text/javascript; charset=utf-8"}
PAGES = {
    "/inbox": ("Inbox", "inbox", "console.inbox:page"),
    "/board": ("Board", "board", "console.board:page"),
    "/system": ("System", "system", "console.system_page:page"),
    "/settings": ("Settings", "system", "console.settings_page:page"),
    "/switch": ("Switch system", "system", "console.switcher:page"),
}
PANELS = {
    "need": "console.inbox:panel_need",
    "spec": "console.panels:panel_spec", "run": "console.panels:panel_run", "issue": "console.panels:panel_issue",
    "instance": "console.panels:panel_instance", "release": "console.panels:panel_release", "stage": "console.panels:panel_stage",
}
PALETTE = "console.palette:fragment"
ASK = "console.palette:ask"
MAX_BODY = 1_000_000


class HttpError(Exception):
    def __init__(self, status: int, error: str, detail: str | None = None, **extra: Any):
        super().__init__(error)
        self.status, self.error, self.detail, self.extra = status, error, detail, extra


class Context:
    """What a view sees of the running console."""

    def __init__(self, repo_dir: Path, sources: dict[str, sources_mod.Source], token: str, mirror: Any = None):
        self.repo_dir, self.sources, self.token, self.mirror = repo_dir, sources, token, mirror

    def snapshot(self, repo: str | None = None) -> Path:
        """The snapshot of `main` of a system repo; the working directory itself until the mirror has one."""
        found = self.mirror.snapshot(repo) if self.mirror is not None else None
        return found or self.repo_dir

    def source(self, name: str) -> sources_mod.Source | None:
        return self.sources.get(name)

    def data(self, name: str) -> Any:
        source = self.sources.get(name)
        return source.data if source else None

    def state(self) -> dict:
        """The document of `GET /api/state` plus the token, as `layout.page` takes it."""
        doc = sources_mod.state(self.sources, actions.summary())
        doc["token"] = self.token
        doc["now"] = sources_mod.utcnow()
        return doc

    def api_state(self) -> dict:
        doc = self.state()
        doc.pop("token")
        doc.pop("now")
        return doc


def resolve(target: str) -> Any:
    """Import `"module:function"`; raises ImportError / AttributeError when the view is not there."""
    module, _, name = target.partition(":")
    return getattr(import_module(module), name)


def missing_view(target: str, error: Exception) -> bool:
    module = target.partition(":")[0]
    if isinstance(error, ModuleNotFoundError):
        return error.name == module
    return isinstance(error, AttributeError) and module in str(error)


def placeholder(ctx: Context, title: str, place: str, target: str) -> str:
    body = f'<p class="empty">This view ({esc(target)}) is not installed in this build of the console.</p>'
    return layout.page(title, place, body, state=ctx.state())


class Handler(BaseHTTPRequestHandler):
    server_version = "cplat-console"
    protocol_version = "HTTP/1.0"

    @property
    def ctx(self) -> Context:
        return self.server.ctx  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    # ---- replies ----
    def reply(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def reply_json(self, status: int, doc: Any) -> None:
        self.reply(status, json.dumps(doc).encode(), "application/json")

    def reply_html(self, status: int, html: str) -> None:
        self.reply(status, html.encode(), "text/html; charset=utf-8")

    def reply_error(self, err: HttpError) -> None:
        self.reply_json(err.status, {"error": err.error, "detail": err.detail, **err.extra})

    # ---- dispatch ----
    def handle_one(self, method: str) -> None:
        try:
            expected = f"127.0.0.1:{self.server.server_address[1]}"
            if self.headers.get("Host") != expected:
                raise HttpError(421, "wrong host", f"expected {expected}")
            url = urlsplit(self.path)
            if method == "POST":
                given = self.headers.get("X-Console-Token") or ""
                if not secrets.compare_digest(given.encode(), self.ctx.token.encode()):
                    raise HttpError(403, "missing or wrong token", "send the console-token of the page as X-Console-Token")
                self.post(url.path)
            else:
                self.get(url.path, {k: v[0] for k, v in parse_qs(url.query, keep_blank_values=True).items()})
        except HttpError as e:
            self.reply_error(e)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as e:  # noqa: BLE001  (a view that crashes must not take the server with it)
            self.reply_error(HttpError(500, "internal error", f"{type(e).__name__}: {e}"))

    def do_GET(self) -> None:  # noqa: N802
        self.handle_one("GET")

    def do_HEAD(self) -> None:  # noqa: N802
        self.handle_one("GET")

    def do_POST(self) -> None:  # noqa: N802
        self.handle_one("POST")

    # ---- GET ----
    def get(self, path: str, query: dict[str, str]) -> None:
        if path == "/":
            self.reply(302, b"", "text/plain", {"Location": "/inbox"})
        elif path in PAGES:
            title, place, target = PAGES[path]
            self.reply_html(200, self.page(title, place, target, query))
        elif path.startswith("/static/"):
            self.static(path[len("/static/"):])
        elif path.startswith("/panel/"):
            self.panel(path[len("/panel/"):])
        elif path == "/palette":
            self.reply_html(200, self.fragment(PALETTE, query.get("q", "")))
        elif path == "/api/state":
            self.reply_json(200, self.ctx.api_state())
        elif path == "/api/actions":
            self.reply_json(200, actions.list_actions())
        elif path.startswith("/api/actions/"):
            found = actions.get(path[len("/api/actions/"):])
            if found is None:
                raise HttpError(404, "no such action", path)
            self.reply_json(200, found)
        else:
            raise HttpError(404, "not found", path)

    def page(self, title: str, place: str, target: str, query: dict[str, str]) -> str:
        try:
            view = resolve(target)
        except (ImportError, AttributeError) as e:
            if missing_view(target, e):
                return placeholder(self.ctx, title, place, target)
            raise
        try:
            return view(self.ctx, query)
        except LookupError as e:
            raise HttpError(404, "not found", str(e)) from e

    def fragment(self, target: str, arg: str) -> str:
        try:
            view = resolve(target)
        except (ImportError, AttributeError) as e:
            if missing_view(target, e):
                raise HttpError(501, "view not installed", target) from e
            raise
        try:
            return view(self.ctx, arg)
        except LookupError as e:
            raise HttpError(404, "not found", str(e)) from e

    def static(self, name: str) -> None:
        if name not in STATIC_FILES:
            raise HttpError(404, "not found", f"/static/{name}")
        self.reply(200, (STATIC / name).read_bytes(), STATIC_FILES[name])

    def panel(self, rest: str) -> None:
        kind, _, ident = rest.partition("/")
        if kind not in PANELS or not ident:
            raise HttpError(404, "not found", f"/panel/{rest}")
        self.reply_html(200, self.fragment(PANELS[kind], unquote(ident)))

    # ---- POST ----
    def body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            raise HttpError(413, "body too large")
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return {}
        try:
            doc = json.loads(raw)
        except ValueError as e:
            raise HttpError(400, "body is not JSON", str(e)) from e
        if not isinstance(doc, dict):
            raise HttpError(400, "body must be a JSON object")
        return doc

    def post(self, path: str) -> None:
        body = self.body()
        retry_source = re.fullmatch(r"/api/sources/([^/]+)/retry", path)
        retry_action = re.fullmatch(r"/api/actions/([^/]+)/retry", path)
        if retry_source:
            source = self.ctx.sources.get(unquote(retry_source.group(1)))
            if source is None:
                raise HttpError(404, "no such source", retry_source.group(1))
            source.read_in_background()
            self.reply_json(202, {})
        elif path == "/api/preview":
            self.reply_json(200, self.preview(body))
        elif path == "/api/actions":
            self.reply_json(202, {"id": self.start(body)})
        elif retry_action:
            self.reply_json(202, {"id": self.retry(unquote(retry_action.group(1)))})
        elif path == "/api/open-in-claude":
            self.reply_json(200, self.open_in_claude(body))
        elif path == "/api/ask":
            question = str(body.get("question") or "").strip()
            if not question:
                raise HttpError(400, "question is empty")
            self.reply_json(200, self.call(ASK, question))
        elif path == "/api/shutdown":
            self.shutdown(body)
        else:
            raise HttpError(404, "not found", path)

    def call(self, target: str, arg: str) -> Any:
        try:
            return resolve(target)(self.ctx, arg)
        except (ImportError, AttributeError) as e:
            if missing_view(target, e):
                raise HttpError(501, "view not installed", target) from e
            raise

    def preview(self, body: dict) -> dict:
        fields = body.get("fields")
        try:
            return preview.preview(self.ctx.snapshot(), str(body.get("form") or ""), fields if isinstance(fields, dict) else {})
        except preview.BadForm as e:
            raise HttpError(400, "bad form", str(e)) from e

    def start(self, body: dict) -> str:
        obj, args = body.get("object"), body.get("args")
        try:
            return actions.start(str(body.get("kind") or ""), obj if isinstance(obj, dict) else {}, args if isinstance(args, dict) else {})
        except ValueError as e:
            raise HttpError(400, "invalid action", str(e)) from e
        except actions.Conflict as e:
            raise HttpError(409, "another action on this object is running", str(e)) from e
        except actions.Missing as e:
            raise HttpError(412, f"{e.needs} is missing", str(e), needs=e.needs) from e

    def retry(self, action_id: str) -> str:
        try:
            return actions.retry(action_id)
        except KeyError as e:
            raise HttpError(404, "no such action", action_id) from e
        except actions.Conflict as e:
            raise HttpError(409, "another action on this object is running", str(e)) from e
        except actions.Missing as e:
            raise HttpError(412, f"{e.needs} is missing", str(e), needs=e.needs) from e

    def open_in_claude(self, body: dict) -> dict:
        run_id = str(body.get("run_id") or "")
        runs = (self.ctx.data("runs") or {}).get("runs", []) if isinstance(self.ctx.data("runs"), dict) else []
        run = next((r for r in runs if r.get("run_id") == run_id), None)
        if run is None:
            raise HttpError(404, "no such run", run_id)
        argv = handoff.claude_command(run, f"docs/specs/{run.get('spec')}/spec.md", run.get("failure"))
        cwd = run.get("repo_dir")
        started = handoff.open_terminal(argv, cwd if cwd and Path(cwd).is_dir() else str(self.ctx.repo_dir))
        return {"command": shlex.join(argv), "started": bool(started)}

    def shutdown(self, body: dict) -> None:
        running = actions.running()
        if running and not body.get("confirm"):
            raise HttpError(409, "actions are running", f"{len(running)} action(s) would be stopped", running=running)
        if running:
            actions.stop_all()
        self.reply_json(202, {})
        stop_later(self.server)


def stop_later(httpd: ThreadingHTTPServer) -> None:
    """Stop `serve_forever` from a thread (calling `shutdown` on the serving thread would wait for itself)."""
    threading.Thread(target=httpd.shutdown, name="stop", daemon=True).start()


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], ctx: Context):
        super().__init__(address, Handler)
        self.ctx = ctx


def make_server(repo_dir: Path, sources: dict[str, sources_mod.Source], *, port: int = 0, mirror: Any = None) -> ConsoleServer:
    """A server on 127.0.0.1 (never another address) with a fresh token; call `serve_forever()` to run it."""
    actions.load()
    return ConsoleServer(("127.0.0.1", port), Context(Path(repo_dir), sources, secrets.token_urlsafe(24), mirror))
