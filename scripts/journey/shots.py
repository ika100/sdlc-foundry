"""Screenshots of what a recorded journey built, for Watch a real run: the web UI, the API docs, Grafana, Argo CD, k9s.

  uv run --with playwright python3 scripts/journey/shots.py <system> [--env prod] [--out site/public/demo/shots]
      [--port 8088] [--k9s PATH]

Run it at the end of a journey while the local cluster (k3d-<system>-local) still runs. It reads the cluster only:
the web UI and the API docs of <env> and Grafana through the Gateway on <port>, Argo CD through a port-forward with the
initial admin password, and k9s (pods in every namespace, read-only) in a detached tmux pane rendered to an image.
The browser is the installed Chrome (Playwright's `chrome` channel), so no browser download is needed. Each shot that
cannot be taken is reported and skipped; the exit code is 1 when none was taken.
"""

import argparse
import base64
import html
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from playwright.sync_api import sync_playwright

VIEW = {"width": 1440, "height": 900}
# requests per second per component, from the metrics every template exposes
GRAFANA_QUERY = "sum by (job) (rate(http_requests_total[5m]))"


def get_json(url: str, data: dict | None = None) -> object:
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    ctx = ssl._create_unverified_context()  # the port-forwarded Argo CD serves a self-signed certificate
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return json.load(r)


def shoot(page, url: str, path: str, settle: float) -> None:
    page.goto(url, wait_until="networkidle", timeout=60_000)
    time.sleep(settle)
    page.screenshot(path=path)


# --- k9s: a tmux pane with its ANSI colours, turned into HTML and photographed like a page

BASE16 = ["#000000", "#cd3131", "#0dbc79", "#e5e510", "#2472c8", "#bc3fbc", "#11a8cd", "#e5e5e5",
          "#666666", "#f14c4c", "#23d18b", "#f5f543", "#3b8eea", "#d670d6", "#29b8db", "#ffffff"]


def color256(n: int) -> str:
    if n < 16:
        return BASE16[n]
    if n < 232:
        n -= 16
        steps = [0, 95, 135, 175, 215, 255]
        return "#%02x%02x%02x" % (steps[n // 36], steps[n // 6 % 6], steps[n % 6])
    v = 8 + (n - 232) * 10
    return "#%02x%02x%02x" % (v, v, v)


def ansi_to_html(text: str) -> str:
    out, fg, bg, bold, rev = [], None, None, False, False
    for part in re.split(r"(\x1b\[[0-9;]*m)", text):
        if not part.startswith("\x1b["):
            if part:
                f, b = (bg or "#1e1e1e", fg or "#d4d4d4") if rev else (fg, bg)
                style = (f"color:{f};" if f else "") + (f"background:{b};" if b else "") + ("font-weight:700;" if bold else "")
                out.append(f'<span style="{style}">{html.escape(part)}</span>' if style else html.escape(part))
            continue
        codes = [int(c) if c else 0 for c in part[2:-1].split(";")]
        i = 0
        while i < len(codes):
            c = codes[i]
            if c == 0:
                fg, bg, bold, rev = None, None, False, False
            elif c == 1:
                bold = True
            elif c == 22:
                bold = False
            elif c == 7:
                rev = True
            elif c == 27:
                rev = False
            elif 30 <= c <= 37 or 90 <= c <= 97:
                fg = BASE16[c - 30 if c < 90 else c - 82]
            elif 40 <= c <= 47 or 100 <= c <= 107:
                bg = BASE16[c - 40 if c < 100 else c - 92]
            elif c == 39:
                fg = None
            elif c == 49:
                bg = None
            elif c in (38, 48) and i + 1 < len(codes):
                if codes[i + 1] == 5 and i + 2 < len(codes):
                    val, i = color256(codes[i + 2]), i + 2
                elif codes[i + 1] == 2 and i + 4 < len(codes):
                    val, i = "#%02x%02x%02x" % tuple(codes[i + 2:i + 5]), i + 4
                else:
                    val = None
                if c == 38:
                    fg = val
                else:
                    bg = val
            i += 1
    return "".join(out)


def k9s_page(k9s: str, context: str) -> str:
    session = f"shots-k9s-{os.getpid()}"
    subprocess.run(["tmux", "new-session", "-d", "-s", session, "-x", "170", "-y", "56",
                    f"TERM=xterm-256color {k9s} --context {context} --readonly -A -c pods"], check=True)
    try:
        time.sleep(10)
        pane = subprocess.run(["tmux", "capture-pane", "-p", "-e", "-t", session], capture_output=True, text=True,
                              check=True).stdout
    finally:
        subprocess.run(["tmux", "kill-session", "-t", session], check=False)
    body = ansi_to_html(pane)
    return ("<html><body style='margin:0;background:#1e1e1e'><pre style='margin:0;padding:16px;color:#d4d4d4;"
            "font:13px/1.25 Menlo,monospace'>" + body + "</pre></body></html>")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("system")
    ap.add_argument("--env", default="prod")
    ap.add_argument("--out", default="site/public/demo/shots")
    ap.add_argument("--port", type=int, default=8088)
    ap.add_argument("--obs-env", default="dev", help="the environment with the observability stack (logs, traces)")
    ap.add_argument("--k9s", default=shutil.which("k9s") or "")
    a = ap.parse_args()
    context, gw = f"k3d-{a.system}-local", f"http://%s.localhost:{a.port}"
    os.makedirs(a.out, exist_ok=True)
    taken, failed = [], []

    def attempt(name: str, fn) -> None:
        try:
            fn(os.path.join(a.out, f"{name}.png"))
            taken.append(name)
        except Exception as e:  # each shot is independent: report it and go on
            failed.append(f"{name}: {e}")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome")
        ctx = browser.new_context(viewport=VIEW, ignore_https_errors=True, color_scheme="light",
                                  locale="en-US")
        page = ctx.new_page()
        ns = f"{a.system}-{a.env}"
        attempt("web", lambda path: shoot(page, gw % f"{a.system}-web.{ns}" + "/", path, 2))
        attempt("api-docs", lambda path: shoot(page, gw % f"{a.system}-api.{ns}" + "/docs", path, 2))

        def grafana(path: str) -> None:
            # Explore, not a stock dashboard: those expect the Java agent's metric names and show "No data"
            ds = [d["uid"] for d in get_json(gw % "grafana" + "/api/datasources") if d["type"] == "prometheus"][0]
            query = {"refId": "A", "expr": GRAFANA_QUERY, "legendFormat": "{{job}}",
                     "datasource": {"type": "prometheus", "uid": ds}}
            panes = {"a": {"datasource": ds, "queries": [query], "range": {"from": "now-3h", "to": "now"}}}
            shoot(page, gw % "grafana" + "/explore?schemaVersion=1&orgId=1&panes="
                  + urllib.parse.quote(json.dumps(panes)), path, 8)
        attempt("grafana", grafana)

        def explore(ds_type: str, query: dict) -> str:
            ds = [d["uid"] for d in get_json(gw % "grafana" + "/api/datasources") if d["type"] == ds_type][0]
            query = {"refId": "A", "datasource": {"type": ds_type, "uid": ds}, **query}
            panes = {"a": {"datasource": ds, "queries": [query], "range": {"from": "now-1h", "to": "now"}}}
            return gw % "grafana" + "/explore?schemaVersion=1&orgId=1&panes=" + urllib.parse.quote(json.dumps(panes))

        obs = f"{a.system}-{a.obs_env}"

        def tempo(path: str) -> None:
            # one real request trace of the API (its database spans included), not the health probes
            proxy = gw % "grafana" + "/api/datasources/proxy/uid/tempo/api/search"
            ql = (f'{{ resource.service.name = "{a.system}-api" && span.http.route != nil'
                  f' && span.http.route !~ "/(health|ready|metrics)" }}')   # probes outnumber requests
            traces = get_json(f"{proxy}?" + urllib.parse.urlencode({"q": ql, "limit": 20}))["traces"]
            if not traces:
                raise RuntimeError(f"no request trace of {a.system}-api in Tempo")
            shoot(page, explore("tempo", {"queryType": "traceql", "query": traces[0]["traceID"]}), path, 8)
        attempt("tempo", tempo)

        def loki(path: str) -> None:
            proxy = gw % "grafana" + "/api/datasources/proxy/uid/loki/loki/api/v1/labels"
            if not get_json(proxy).get("data"):
                raise RuntimeError("Loki holds no logs (nothing ships the pods' logs to it)")
            shoot(page, explore("loki", {"expr": f'{{namespace="{obs}"}}', "queryType": "range"}), path, 8)
        attempt("loki", loki)

        def argocd(path: str) -> None:
            pw = subprocess.run(["kubectl", "--context", context, "-n", "argocd", "get", "secret",
                                 "argocd-initial-admin-secret", "-o", "jsonpath={.data.password}"],
                                capture_output=True, text=True, check=True).stdout
            fwd = subprocess.Popen(["kubectl", "--context", context, "-n", "argocd", "port-forward",
                                    "svc/argocd-server", "18089:443"], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
            try:
                time.sleep(3)
                token = get_json("https://localhost:18089/api/v1/session",
                                 {"username": "admin", "password": base64.b64decode(pw).decode()})["token"]
                ctx.add_cookies([{"name": "argocd.token", "value": token, "url": "https://localhost:18089"}])
                shoot(page, f"https://localhost:18089/applications?view=list&search={a.system}-", path, 4)
            finally:
                fwd.terminate()
        attempt("argocd", argocd)

        def k9s(path: str) -> None:
            if not a.k9s:
                raise RuntimeError("k9s not found; pass --k9s")
            page.set_content(k9s_page(a.k9s, context))
            page.screenshot(path=path, full_page=True)
        attempt("k9s", k9s)
        browser.close()

    for name in taken:
        print(f"OK   {os.path.join(a.out, name + '.png')}")
    for f in failed:
        print(f"SKIP {f}")
    return 0 if taken else 1


if __name__ == "__main__":
    sys.exit(main())
