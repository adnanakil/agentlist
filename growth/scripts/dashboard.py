"""HAL growth team dashboard — local, read-only, stdlib-only (runs on /usr/bin/python3).

Serves http://127.0.0.1:8787 with live status, spend/households charts, cycle
reports (the team's decisions), the experiment ledger, and activity logs.
Reads growth/ files fresh on every request; writes nothing.
"""
import datetime as dt
import html
import json
import pathlib
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = pathlib.Path("/Users/adnanakil/Project/agentlist")
G = REPO / "growth"
PORT = 8787
CAP_USD = 30.0
CYCLE_HOURS = 6

# ---------- tiny markdown renderer (headers, tables, lists, bold, code, links) ----------

def md_to_html(text):
    out, lines = [], text.splitlines()
    i, in_code, in_list = 0, False, False

    def inline(s):
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    def close_list():
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    while i < len(lines):
        raw = html.escape(lines[i], quote=False)
        if raw.startswith("```"):
            close_list()
            out.append("<pre>" if not in_code else "</pre>")
            in_code = not in_code
            i += 1
            continue
        if in_code:
            out.append(raw)
            i += 1
            continue
        if raw.startswith("|"):
            close_list()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in html.escape(lines[i], quote=False).strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            out.append("<table>")
            for ri, row in enumerate(rows):
                tag = "th" if ri == 0 else "td"
                out.append("<tr>" + "".join("<%s>%s</%s>" % (tag, inline(c), tag) for c in row) + "</tr>")
            out.append("</table>")
            continue
        m = re.match(r"(#{1,4}) (.*)", raw)
        if m:
            close_list()
            n = len(m.group(1)) + 1
            out.append("<h%d>%s</h%d>" % (n, inline(m.group(2)), n))
        elif raw.startswith("- ") or raw.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append("<li>%s</li>" % inline(raw[2:]))
        elif raw.strip() in ("---", "***"):
            close_list()
            out.append("<hr>")
        elif raw.strip() == "":
            close_list()
        else:
            close_list()
            out.append("<p>%s</p>" % inline(raw))
        i += 1
    close_list()
    if in_code:
        out.append("</pre>")
    return "\n".join(out)

# ---------- data ----------

def load_metrics():
    p = G / "state/metrics-latest.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return None


def supervisor_status():
    log = G / "state/supervisor.log"
    last_tick = None
    if log.exists():
        for line in reversed(log.read_text().splitlines()[-200:]):
            m = re.match(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]", line)
            if m:
                last_tick = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
                break
    alive = last_tick is not None and (dt.datetime.now() - last_tick) < dt.timedelta(minutes=40)
    cycling = subprocess.run(
        ["pgrep", "-f", "claude -p /growth-daily"], capture_output=True
    ).returncode == 0
    lc = G / "state/last_cycle"
    last_cycle = dt.datetime.fromtimestamp(float(lc.read_text().strip())) if lc.exists() else None
    return alive, cycling, last_tick, last_cycle

# ---------- chart ----------

def bar_chart(days, values, css_var, value_fmt, label_nonzero=False):
    W, H, PADL, PADB, PADT = 760, 150, 44, 22, 14
    plot_w, plot_h = W - PADL - 8, H - PADB - PADT
    vmax = max(values + [1e-9])
    nice = max(1.0, float("%.0g" % (vmax * 1.25))) if vmax > 0 else 1.0
    if nice < vmax:
        nice *= 2
    n = len(days)
    slot = plot_w / n
    bw = max(4.0, slot - 4)  # >=2px gap each side between adjacent bars
    parts = ['<svg viewBox="0 0 %d %d" role="img">' % (W, H)]
    for frac in (0.5, 1.0):
        y = PADT + plot_h * (1 - frac)
        parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="grid"/>' % (PADL, y, W - 8, y))
        parts.append('<text x="%d" y="%.1f" class="tick" text-anchor="end">%s</text>'
                     % (PADL - 6, y + 4, value_fmt(nice * frac)))
    parts.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" class="axis"/>'
                 % (PADL, PADT + plot_h, W - 8, PADT + plot_h))
    imax = values.index(max(values)) if vmax > 0 else -1
    for i, (day, v) in enumerate(zip(days, values)):
        x = PADL + i * slot + (slot - bw) / 2
        h = plot_h * (v / nice)
        y = PADT + plot_h - h
        if v > 0:
            r = min(4, h / 2, bw / 2)
            parts.append(
                '<path d="M%.1f %.1f V%.1f Q%.1f %.1f %.1f %.1f H%.1f Q%.1f %.1f %.1f %.1f V%.1f Z" fill="var(%s)"/>'
                % (x, PADT + plot_h, y + r, x, y, x + r, y, x + bw - r, x + bw, y, x + bw, y + r,
                   PADT + plot_h, css_var)
            )
        if v > 0 and (i == imax or label_nonzero):
            parts.append('<text x="%.1f" y="%.1f" class="lbl" text-anchor="middle">%s</text>'
                         % (x + bw / 2, y - 4, value_fmt(v)))
        if i % 2 == 0:
            parts.append('<text x="%.1f" y="%d" class="tick" text-anchor="middle">%s</text>'
                         % (x + bw / 2, H - 6, day[5:]))
        parts.append(
            '<rect x="%.1f" y="%d" width="%.1f" height="%d" fill="transparent" '
            'class="hit" data-day="%s" data-val="%s"/>'
            % (PADL + i * slot, PADT, slot, plot_h, day, value_fmt(v))
        )
    parts.append("</svg>")
    return "".join(parts)

# ---------- page ----------

CSS = """
:root{color-scheme:light;
  --page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
  --grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,0.10);
  --series-1:#2a78d6;--series-2:#eb6834;
  --good:#0ca30c;--warning:#fab219;--critical:#d03b3b;}
@media (prefers-color-scheme: dark){:root{color-scheme:dark;
  --page:#0d0d0d;--surface:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;
  --grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,0.10);
  --series-1:#3987e5;--series-2:#d95926;}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--ink);
  font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:20px 16px 60px;}
.wrap{max-width:820px;margin:0 auto}
h1{font-size:19px;margin:0 0 2px}
.sub{color:var(--ink2);margin:0 0 18px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;
  padding:14px 16px;margin-bottom:14px;overflow-x:auto}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:10px;margin-bottom:14px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:10px 12px}
.tile .k{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.tile .v{font-size:21px;margin-top:2px}
.tile .s{color:var(--ink2);font-size:11px;margin-top:1px}
.status-good{color:var(--good)}.status-critical{color:var(--critical)}.status-warning{color:var(--warning)}
.charttitle{display:flex;align-items:center;gap:7px;font-weight:600;margin:2px 0 6px}
.chip{width:10px;height:10px;border-radius:3px;display:inline-block}
svg{width:100%;height:auto;display:block}
.grid{stroke:var(--grid);stroke-width:1}
.axis{stroke:var(--axis);stroke-width:1}
.tick{fill:var(--muted);font-size:10px}
.lbl{fill:var(--ink2);font-size:11px}
#tt{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--border);
  border-radius:6px;padding:4px 8px;font-size:12px;display:none;box-shadow:0 2px 8px rgba(0,0,0,.15)}
details{margin-bottom:8px}
summary{cursor:pointer;font-weight:600}
table{border-collapse:collapse;margin:8px 0;font-size:13px}
th,td{border:1px solid var(--grid);padding:3px 9px;text-align:left}
th{color:var(--ink2)}
td{font-variant-numeric:tabular-nums}
pre{background:var(--page);border:1px solid var(--border);border-radius:6px;
  padding:8px 10px;font-size:12px;overflow-x:auto;white-space:pre-wrap}
code{background:var(--page);padding:0 4px;border-radius:4px;font-size:12.5px}
h2{font-size:16px;margin:4px 0 8px}h3{font-size:14px;margin:10px 0 4px}h4,h5{font-size:13px;margin:8px 0 4px}
a{color:var(--series-1)}
hr{border:none;border-top:1px solid var(--grid);margin:10px 0}
.muted{color:var(--muted)}
"""

JS = """
var tt=document.getElementById('tt');
document.querySelectorAll('.hit').forEach(function(r){
  r.addEventListener('mousemove',function(e){
    tt.style.display='block';
    tt.innerHTML='<strong>'+r.dataset.day+'</strong> · '+r.dataset.val;
    tt.style.left=Math.min(e.clientX+12,window.innerWidth-140)+'px';
    tt.style.top=(e.clientY+12)+'px';});
  r.addEventListener('mouseleave',function(){tt.style.display='none';});
});
"""


def tile(k, v, s="", cls=""):
    return ('<div class="tile"><div class="k">%s</div><div class="v %s">%s</div>'
            '<div class="s">%s</div></div>' % (k, cls, v, s))


def build_page():
    m = load_metrics()
    alive, cycling, last_tick, last_cycle = supervisor_status()

    today = dt.date.today()
    days = [str(today - dt.timedelta(days=i)) for i in range(13, -1, -1)]
    spend_by_day = (m or {}).get("spend_by_day", {})
    new_by_day = (m or {}).get("new_by_day", {})
    spend = [float(spend_by_day.get(d, {}).get("cost_usd", 0.0)) for d in days]
    news = [int(new_by_day.get(d, 0)) for d in days]

    if alive and cycling:
        sup_v, sup_cls, sup_s = "● Running", "status-good", "cycle in progress now"
    elif alive:
        nxt = (last_cycle + dt.timedelta(hours=CYCLE_HOURS)).strftime("%H:%M") if last_cycle else "?"
        sup_v, sup_cls, sup_s = "● Running", "status-good", "next cycle ~" + nxt
    else:
        sup_v, sup_cls, sup_s = "■ Stopped", "status-critical", "no watchdog tick > 40 min"

    tiles = [tile("Supervisor", sup_v, sup_s, sup_cls)]
    if m:
        cpa = m.get("naive_cpa_usd")
        tiles += [
            tile("Households", str(m.get("total_households", "?")), "all time"),
            tile("New (14d)", str(m.get("window_new_households", "?")), "first text to HAL"),
            tile("Ad spend (14d)", "$%.2f" % m.get("window_spend_usd", 0.0),
                 "%d paid clicks" % m.get("window_clicks", 0)),
            tile("Naive CPA", "$%.2f" % cpa if cpa else "n/a", "organic mixed in"),
            tile("Today's spend", "$%.2f" % spend[-1], "cap $%.0f/day" % CAP_USD),
        ]
    scoreboard_note = "" if m else '<p class="muted">No metrics yet — first cycle pending.</p>'

    reports = sorted(
        (p for p in G.glob("reports/*.md") if not p.name.startswith("scoreboard-")),
        key=lambda p: p.name, reverse=True,
    )
    rep_html = []
    for i, p in enumerate(reports[:14]):
        body = md_to_html(p.read_text())
        rep_html.append("<details%s><summary>%s</summary>%s</details>"
                        % (" open" if i == 0 else "", html.escape(p.stem), body))
    if not rep_html:
        rep_html.append('<p class="muted">No cycle reports yet — the first one lands when the '
                        'running cycle finishes.</p>')

    exp_p = G / "state/experiments.md"
    exp_html = md_to_html(exp_p.read_text()) if exp_p.exists() else '<p class="muted">No ledger.</p>'

    sup_log = G / "state/supervisor.log"
    log_tail = "\n".join(sup_log.read_text().splitlines()[-25:]) if sup_log.exists() else ""
    cyc_log = G / "state/cycle.log"
    cyc_tail = cyc_log.read_text()[-3000:] if cyc_log.exists() and cyc_log.stat().st_size else ""

    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="90"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HAL Growth</title><style>%s</style></head><body><div class="wrap">
<h1>HAL Growth Team</h1><p class="sub">texthal.com · $%.0f/day cap · rendered %s (auto-refreshes)</p>
<div class="tiles">%s</div>%s
<div class="card"><div class="charttitle"><span class="chip" style="background:var(--series-1)"></span>Ad spend per day (USD)</div>%s</div>
<div class="card"><div class="charttitle"><span class="chip" style="background:var(--series-2)"></span>New households per day</div>%s</div>
<div class="card"><h2>Cycle reports — decisions &amp; changes</h2>%s</div>
<div class="card"><h2>Experiment ledger — what it's trying</h2>%s</div>
<div class="card"><h2>Activity log</h2><pre>%s</pre>%s</div>
</div><div id="tt"></div><script>%s</script></body></html>""" % (
        CSS, CAP_USD, stamp, "".join(tiles), scoreboard_note,
        bar_chart(days, spend, "--series-1", lambda v: "$%.2f" % v),
        bar_chart(days, news, "--series-2", lambda v: "%d" % round(v), label_nonzero=True),
        "".join(rep_html), exp_html,
        html.escape(log_tail),
        ("<h3>Last cycle output (tail)</h3><pre>%s</pre>" % html.escape(cyc_tail)) if cyc_tail else "",
        JS,
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/index.html"):
            self.send_response(404)
            self.end_headers()
            return
        try:
            page = build_page().encode()
        except Exception as e:  # never let a bad file take the dashboard down
            page = ("<pre>dashboard render error: %s</pre>" % html.escape(str(e))).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    import os
    bind = os.environ.get("DASH_BIND", "127.0.0.1")  # hal sets 0.0.0.0 for LAN access
    ThreadingHTTPServer((bind, PORT), Handler).serve_forever()
