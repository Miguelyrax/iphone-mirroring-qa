#!/usr/bin/env python3
"""Genera runs/<run>/reporte.html a partir de steps.jsonl + issues.jsonl.

  report.py [ruta_run]     (por defecto, el run activo)
"""
import html
import json
import os
import statistics
import subprocess
import sys
from collections import Counter, OrderedDict, defaultdict

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
import qa  # noqa: E402  (reutiliza los detectores de idioma/UI)

SEV_ORDER = {"alta": 0, "media": 1, "baja": 2}
SEV_LABEL = {"alta": "Alta", "media": "Media", "baja": "Baja"}
SEV_ICON = {"alta": "▲", "media": "◆", "baja": "●"}
CAT_LABEL = {
    "error": "Error / fallo", "datos": "Datos inconsistentes", "i18n": "Idioma (no español)",
    "ortografia": "Ortografía", "texto": "Redacción / consistencia", "formato": "Formato de números y fechas",
    "ux": "Experiencia de uso", "ui": "Visual / layout", "rendimiento": "Rendimiento",
    "navegacion": "Navegación", "interaccion": "Interacción / toque", "contenido": "Contenido",
}
SLOW = 3.0


def esc(s):
    return html.escape(str(s), quote=True)


def load(rd):
    steps = [json.loads(l) for l in open(os.path.join(rd, "steps.jsonl")) if l.strip()]
    ip = os.path.join(rd, "issues.jsonl")
    issues = [json.loads(l) for l in open(ip) if l.strip()] if os.path.exists(ip) else []
    meta = json.load(open(os.path.join(rd, "meta.json")))
    for s in steps:  # recalcula con los detectores actuales (corrige falsos positivos de pasos viejos)
        s["english"] = qa.english_findings(s["ocr"])
        s["ui"] = qa.ui_findings(s["ocr"])
    return steps, issues, meta


def make_thumbs(rd, steps):
    td = os.path.join(rd, "thumbs")
    os.makedirs(td, exist_ok=True)
    for s in steps:
        src = os.path.join(rd, s["shot"])
        dst = os.path.join(td, os.path.basename(s["shot"]).replace(".png", ".jpg"))
        if os.path.exists(src) and not os.path.exists(dst):
            subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "70", "-Z", "560", src,
                            "--out", dst], capture_output=True)
        s["thumb"] = "thumbs/" + os.path.basename(dst)


def is_transition(s):
    return s["action"] != "captura" and not s["action"].startswith("scroll")


def lang_findings(steps):
    seen = OrderedDict()
    for s in steps:
        for f in s["english"]:
            key = f["text"].strip()
            if key not in seen:
                seen[key] = {"f": f, "steps": []}
            seen[key]["steps"].append(s)
    return seen


def accent_findings(steps):
    seen = OrderedDict()
    for s in steps:
        for f in s["ui"]:
            if not f["reason"].startswith("falta tilde"):
                continue
            key = f["reason"]
            seen.setdefault(key, {"f": f, "steps": [], "texts": set()})
            seen[key]["steps"].append(s)
            seen[key]["texts"].add(f["text"])
    return seen


def shot_fig(s, boxes=(), cls="shot"):
    """Miniatura clicable; las cajas (coords normalizadas) se dibujan sobre la imagen."""
    marks = "".join(
        f'<span class="box" style="left:{b["x"]*100:.2f}%;top:{b["y"]*100:.2f}%;'
        f'width:{b["w"]*100:.2f}%;height:{b["h"]*100:.2f}%"></span>' for b in boxes)
    data_boxes = esc(json.dumps([{k: b[k] for k in ("x", "y", "w", "h")} for b in boxes]))
    return (f'<button class="{cls}" data-full="{esc(s["shot"])}" data-boxes="{data_boxes}" '
            f'data-cap="#{s["idx"]} · {esc(s["flow"])} · {esc(s["desc"])}" '
            f'aria-label="Ampliar captura del paso {s["idx"]}">'
            f'<img loading="lazy" src="{esc(s["thumb"])}" alt="Paso {s["idx"]}: {esc(s["desc"])}">{marks}</button>')


def sev_badge(sev):
    return f'<span class="sev sev-{sev}"><span aria-hidden="true">{SEV_ICON[sev]}</span> {SEV_LABEL[sev]}</span>'


def build(rd):
    steps, issues, meta = load(rd)
    make_thumbs(rd, steps)
    by_idx = {s["idx"]: s for s in steps}
    issues = [i for i in issues if i.get("step") in by_idx]
    issues.sort(key=lambda i: (SEV_ORDER.get(i["severity"], 9), i["step"]))
    for n, i in enumerate(issues, 1):
        i["id"] = f"H{n:02d}"

    flows = OrderedDict()
    for s in steps:
        flows.setdefault(s["flow"], []).append(s)
    issues_by_step = defaultdict(list)
    for i in issues:
        issues_by_step[i["step"]].append(i)

    trans = [s for s in steps if is_transition(s)]
    timed = [s for s in trans if not s.get("timed_out")]
    timeouts = [s for s in trans if s.get("timed_out")]
    times = [s["load_time"] for s in timed]
    p90 = sorted(times)[int(len(times) * 0.9) - 1] if times else 0
    slow = sorted([s for s in trans if s["load_time"] > SLOW], key=lambda s: -s["load_time"])
    sev_count = Counter(i["severity"] for i in issues)
    cat_count = Counter(i["category"] for i in issues)
    lang = lang_findings(steps)
    accents = accent_findings(steps)
    errors = [i for i in issues if i["category"] == "error"]
    first_ts, last_ts = steps[0]["ts"], steps[-1]["ts"]

    # ---------- secciones ----------
    kpis = f"""
    <div class="kpis">
      <div class="kpi"><div class="kpi-n">{len(steps)}</div><div class="kpi-l">pantallas capturadas</div></div>
      <div class="kpi"><div class="kpi-n">{len(flows)}</div><div class="kpi-l">flujos recorridos</div></div>
      <div class="kpi"><div class="kpi-n">{len(issues)}</div><div class="kpi-l">hallazgos</div>
        <div class="kpi-sub">{sev_badge('alta')} {sev_count['alta']} &nbsp; {sev_badge('media')} {sev_count['media']} &nbsp; {sev_badge('baja')} {sev_count['baja']}</div></div>
      <div class="kpi"><div class="kpi-n">{len(errors)}</div><div class="kpi-l">errores funcionales</div></div>
      <div class="kpi"><div class="kpi-n">{len(lang)}</div><div class="kpi-l">textos no en español (detección automática)</div></div>
      <div class="kpi"><div class="kpi-n">{statistics.median(times):.1f} s</div><div class="kpi-l">mediana entre pantallas</div>
        <div class="kpi-sub">p90 {p90:.1f} s · {len(slow)} transiciones &gt; {SLOW:.0f} s · {len(timeouts)} nunca se estabilizaron</div></div>
    </div>"""

    top_issues = [i for i in issues if i["severity"] == "alta"]
    summary_list = "".join(
        f'<li><a href="#{i["id"]}">{i["id"]}</a> {esc(i["desc"] if len(i["desc"]) < 200 else i["desc"][:197].rsplit(" ", 1)[0] + "…")}</li>' for i in top_issues)

    cats_opts = "".join(f'<option value="{c}">{esc(CAT_LABEL.get(c, c))} ({n})</option>'
                        for c, n in cat_count.most_common())
    issue_cards = []
    for i in issues:
        s = by_idx[i["step"]]
        issue_cards.append(f"""
      <article class="issue" id="{i['id']}" data-sev="{i['severity']}" data-cat="{i['category']}">
        {shot_fig(s)}
        <div class="issue-body">
          <div class="issue-head">{sev_badge(i['severity'])}<span class="tag">{esc(CAT_LABEL.get(i['category'], i['category']))}</span>
            <span class="muted">{i['id']} · flujo <b>{esc(s['flow'])}</b> · paso #{s['idx']}</span></div>
          <p>{esc(i['desc'])}</p>
        </div>
      </article>""")

    error_cards = "".join(f"""
      <article class="err">
        {shot_fig(by_idx[i['step']], cls='shot big')}
        <div><div class="issue-head">{sev_badge(i['severity'])}<a href="#{i['id']}">{i['id']}</a>
          <span class="muted">flujo <b>{esc(i['flow'])}</b> · paso #{i['step']}</span></div>
          <p>{esc(i['desc'])}</p>
          <p class="muted">Pasos previos: {' → '.join(esc(x['desc']) for x in steps if x['flow'] == i['flow'] and x['idx'] <= i['step'])[-600:]}</p>
        </div>
      </article>""" for i in errors)

    lang_rows = []
    for text, d in lang.items():
        s0 = d["steps"][0]
        flows_l = sorted({x["flow"] for x in d["steps"]})
        lang_rows.append(f"""
        <tr><td>{shot_fig(s0, [d['f']], cls='shot mini')}</td>
          <td><q>{esc(text)}</q><div class="muted">{esc(d['f']['reason'])}</div></td>
          <td>{esc(', '.join(flows_l))}</td><td>{', '.join('#'+str(x['idx']) for x in d['steps'][:8])}{'…' if len(d['steps'])>8 else ''}</td></tr>""")
    acc_rows = "".join(
        f"<tr><td>{shot_fig(d['steps'][0], [d['f']], cls='shot mini')}</td><td>{esc(k.replace('falta tilde: ', ''))}</td>"
        f"<td>{esc(' · '.join(sorted(d['texts']))[:220])}</td><td>{len(d['steps'])}</td></tr>"
        for k, d in accents.items())
    i18n_issues = "".join(f'<li>{sev_badge(i["severity"])} <a href="#{i["id"]}">{i["id"]}</a> {esc(i["desc"])}</li>'
                          for i in issues if i["category"] in ("i18n",))

    # gráfico de barras: transiciones más lentas (una serie, un tono; >25 s se marca como "sin estabilizar")
    top_slow = slow[:18]
    vmax = max([s["load_time"] for s in top_slow] + [1])
    bars = "".join(f"""
        <div class="bar-row" tabindex="0" data-tip="#{s['idx']} · {esc(s['flow'])} · {esc(s['desc'])} — {s['load_time']:.1f} s{' (no se estabilizó)' if s.get('timed_out') else ''}">
          <div class="bar-label">{esc(s['flow'])} · {esc(s['desc'])}</div>
          <div class="bar-track"><div class="bar{' bar-timeout' if s.get('timed_out') else ''}" style="width:{s['load_time']/vmax*100:.1f}%"></div></div>
          <div class="bar-val">{s['load_time']:.1f} s{' ⏳' if s.get('timed_out') else ''}</div>
        </div>""" for s in top_slow)
    t_rows = "".join(
        f"<tr><td>#{s['idx']}</td><td>{esc(s['flow'])}</td><td>{esc(s['desc'])}</td><td class='num'>{s['load_time']:.2f}</td>"
        f"<td>{'no se estabilizó' if s.get('timed_out') else ('lento' if s['load_time']>SLOW else '')}</td></tr>"
        for s in sorted(trans, key=lambda s: -s["load_time"]))
    flow_avg = sorted(((f, statistics.mean([s["load_time"] for s in ss if is_transition(s)] or [0]),
                        len([s for s in ss if is_transition(s)])) for f, ss in flows.items()), key=lambda x: -x[1])
    flow_avg_rows = "".join(f"<tr><td>{esc(f)}</td><td class='num'>{a:.2f}</td><td class='num'>{n}</td></tr>"
                            for f, a, n in flow_avg if n)

    no_effect = [s for s in steps if s["action"] != "captura" and not s.get("changed", True)]
    no_effect_rows = "".join(
        f"<li>#{s['idx']} <b>{esc(s['flow'])}</b> — {esc(s['desc'])}"
        f"{' · <a href=#'+issues_by_step[s['idx']][0]['id']+'>'+issues_by_step[s['idx']][0]['id']+'</a>' if issues_by_step.get(s['idx']) else ''}</li>"
        for s in no_effect)

    flow_html = []
    for f, ss in flows.items():
        nerr = sum(len(issues_by_step[s["idx"]]) for s in ss)
        cells = []
        for s in ss:
            iss = issues_by_step.get(s["idx"], [])
            worst = min((SEV_ORDER[i["severity"]] for i in iss), default=None)
            badge = ""
            if iss:
                sev = ["alta", "media", "baja"][worst]
                badge = f'<a class="pill sev-{sev}" href="#{iss[0]["id"]}">{len(iss)} hallazgo{"s" if len(iss)>1 else ""}</a>'
            t = "" if not is_transition(s) else (
                f'<span class="time {"slow" if s["load_time"]>SLOW else ""}">{"⏳ " if s.get("timed_out") else ""}{s["load_time"]:.1f} s</span>')
            lang_b = f'<span class="pill lang">{len(s["english"])} idioma</span>' if s["english"] else ""
            cells.append(f'<figure class="step {"has-issue" if iss else ""}">{shot_fig(s, s["english"])}'
                         f'<figcaption><b>#{s["idx"]}</b> {esc(s["desc"])}<div class="step-meta">{t}{badge}{lang_b}</div></figcaption></figure>')
        flow_html.append(f"""
      <details class="flow" {'open' if nerr else ''}>
        <summary><span class="flow-name">{esc(f)}</span><span class="muted">{len(ss)} pantallas · {nerr} hallazgos</span></summary>
        <div class="strip">{''.join(cells)}</div>
      </details>""")

    doc = f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QA Offshore</title>
<style>
:root {{
  color-scheme: light;
  --bg: #f4f4f2; --surface: #fcfcfb; --surface-2: #ffffff;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #77756f;
  --line: #e1e0d9; --ring: rgba(11,11,11,.10);
  --accent: #2a78d6; --bar: #2a78d6; --bar-timeout: #77756f;
  --crit: #d03b3b; --serious: #ec835a; --warn: #fab219; --good: #0ca30c;
  --box: #d03b3b; --lang: #4a3aa7;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --bg: #121211; --surface: #1a1a19; --surface-2: #222220;
    --ink: #ffffff; --ink-2: #c3c2b7; --muted: #9a998f;
    --line: #2c2c2a; --ring: rgba(255,255,255,.10);
    --accent: #3987e5; --bar: #3987e5; --bar-timeout: #9a998f; --lang: #9085e9;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --bg: #121211; --surface: #1a1a19; --surface-2: #222220;
  --ink: #ffffff; --ink-2: #c3c2b7; --muted: #9a998f;
  --line: #2c2c2a; --ring: rgba(255,255,255,.10);
  --accent: #3987e5; --bar: #3987e5; --bar-timeout: #9a998f; --lang: #9085e9;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
a {{ color: var(--accent); }}
.wrap {{ max-width: 1180px; margin: 0 auto; padding: 24px 16px 80px; }}
header.top {{ display: flex; flex-wrap: wrap; gap: 8px 24px; align-items: baseline; justify-content: space-between; }}
h1 {{ font-size: 28px; margin: 0; letter-spacing: -.01em; }}
h2 {{ font-size: 20px; margin: 48px 0 12px; padding-top: 8px; border-top: 1px solid var(--line); }}
h3 {{ font-size: 16px; margin: 24px 0 8px; }}
h4 {{ font-size: 14px; margin: 0 0 8px; }}
.muted {{ color: var(--muted); font-size: 13px; }}
nav.toc {{ position: sticky; top: 0; z-index: 5; background: var(--bg); padding: 10px 0; display: flex; gap: 6px; overflow-x: auto; border-bottom: 1px solid var(--line); }}
nav.toc a {{ white-space: nowrap; padding: 4px 10px; border-radius: 999px; background: var(--surface); box-shadow: inset 0 0 0 1px var(--ring); text-decoration: none; color: var(--ink-2); font-size: 13px; }}
.kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; margin: 20px 0; }}
.kpi {{ background: var(--surface); border-radius: 10px; padding: 14px; box-shadow: inset 0 0 0 1px var(--ring); }}
.kpi-n {{ font-size: 30px; font-weight: 650; font-variant-numeric: tabular-nums; }}
.kpi-l {{ color: var(--ink-2); font-size: 13px; }}
.kpi-sub {{ margin-top: 6px; font-size: 12px; color: var(--muted); }}
.sev {{ display: inline-flex; gap: 4px; align-items: center; font-size: 12px; font-weight: 600; padding: 1px 8px; border-radius: 999px; color: var(--ink); background: var(--surface-2); box-shadow: inset 0 0 0 1px var(--ring); white-space: nowrap; }}
.sev-alta > span {{ color: var(--crit); }} .sev-media > span {{ color: var(--serious); }} .sev-baja > span {{ color: var(--warn); }}
.tag {{ font-size: 12px; padding: 1px 8px; border-radius: 999px; background: var(--surface-2); box-shadow: inset 0 0 0 1px var(--ring); color: var(--ink-2); }}
.callout {{ background: var(--surface); border-radius: 10px; padding: 14px 18px; box-shadow: inset 0 0 0 1px var(--ring); }}
.callout li {{ margin: 4px 0; }}
.filters {{ display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin: 8px 0 14px; }}
.filters button, .filters select {{ font: inherit; font-size: 13px; padding: 4px 12px; border-radius: 999px; border: 0; background: var(--surface); color: var(--ink); box-shadow: inset 0 0 0 1px var(--ring); cursor: pointer; }}
.filters button[aria-pressed="true"] {{ background: var(--ink); color: var(--bg); }}
.issue {{ display: grid; grid-template-columns: 110px 1fr; gap: 14px; background: var(--surface); border-radius: 10px; padding: 12px; margin-bottom: 10px; box-shadow: inset 0 0 0 1px var(--ring); scroll-margin-top: 60px; }}
.issue:target {{ box-shadow: inset 0 0 0 2px var(--accent); }}
.issue p {{ margin: 6px 0 0; }}
.issue-head {{ display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; }}
.shot {{ position: relative; display: block; padding: 0; border: 0; background: none; cursor: zoom-in; border-radius: 8px; overflow: hidden; box-shadow: 0 0 0 1px var(--ring); width: 100%; }}
.shot img {{ display: block; width: 100%; height: auto; }}
.shot.mini {{ width: 84px; }}
.shot.big {{ width: 220px; }}
.box {{ position: absolute; outline: 2px solid var(--box); outline-offset: 1px; border-radius: 2px; pointer-events: none; }}
.err {{ display: grid; grid-template-columns: 220px 1fr; gap: 18px; background: var(--surface); border-radius: 10px; padding: 14px; margin-bottom: 12px; box-shadow: inset 0 0 0 1px var(--ring); }}
table {{ width: 100%; border-collapse: collapse; background: var(--surface); border-radius: 10px; overflow: hidden; box-shadow: inset 0 0 0 1px var(--ring); font-size: 14px; }}
th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }}
th {{ font-size: 12px; color: var(--ink-2); font-weight: 600; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.table-scroll {{ overflow-x: auto; }}
.chart {{ background: var(--surface); border-radius: 10px; padding: 14px; box-shadow: inset 0 0 0 1px var(--ring); }}
.bar-row {{ display: grid; grid-template-columns: minmax(120px, 38%) 1fr 72px; gap: 10px; align-items: center; padding: 4px 0; border-radius: 4px; }}
.bar-row:hover, .bar-row:focus {{ background: var(--surface-2); outline: none; }}
.bar-label {{ font-size: 13px; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.bar-track {{ height: 14px; position: relative; }}
.bar {{ height: 100%; background: var(--bar); border-radius: 0 4px 4px 0; min-width: 2px; }}
.bar-timeout {{ background: repeating-linear-gradient(135deg, var(--bar-timeout) 0 4px, transparent 4px 7px); box-shadow: inset 0 0 0 1px var(--bar-timeout); }}
.bar-val {{ font-size: 13px; text-align: right; font-variant-numeric: tabular-nums; }}
.legend {{ display: flex; gap: 16px; font-size: 12px; color: var(--ink-2); margin-top: 10px; flex-wrap: wrap; }}
.legend i {{ display: inline-block; width: 14px; height: 10px; border-radius: 2px; margin-right: 6px; vertical-align: middle; }}
#tip {{ position: fixed; pointer-events: none; z-index: 30; background: var(--ink); color: var(--bg); font-size: 12px; padding: 6px 8px; border-radius: 6px; max-width: 320px; display: none; }}
.flow {{ background: var(--surface); border-radius: 10px; margin-bottom: 10px; box-shadow: inset 0 0 0 1px var(--ring); }}
.flow summary {{ padding: 12px 14px; cursor: pointer; display: flex; gap: 12px; align-items: baseline; flex-wrap: wrap; }}
.flow-name {{ font-weight: 600; }}
.strip {{ display: flex; gap: 12px; overflow-x: auto; padding: 4px 14px 16px; scroll-snap-type: x proximity; }}
.step {{ margin: 0; flex: 0 0 150px; scroll-snap-align: start; }}
.step.has-issue .shot {{ box-shadow: 0 0 0 2px var(--crit); }}
.step figcaption {{ font-size: 12px; margin-top: 6px; color: var(--ink-2); }}
.step-meta {{ display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }}
.time {{ font-size: 11px; padding: 0 6px; border-radius: 999px; box-shadow: inset 0 0 0 1px var(--ring); font-variant-numeric: tabular-nums; }}
.time.slow {{ font-weight: 700; color: var(--ink); box-shadow: inset 0 0 0 1px var(--serious); }}
.pill {{ font-size: 11px; padding: 0 6px; border-radius: 999px; text-decoration: none; color: var(--ink); box-shadow: inset 0 0 0 1px var(--ring); }}
.pill.sev-alta {{ box-shadow: inset 0 0 0 1.5px var(--crit); }} .pill.sev-media {{ box-shadow: inset 0 0 0 1.5px var(--serious); }} .pill.sev-baja {{ box-shadow: inset 0 0 0 1.5px var(--warn); }}
.pill.lang {{ box-shadow: inset 0 0 0 1.5px var(--lang); }}
dialog {{ border: 0; padding: 0; background: transparent; max-width: 96vw; max-height: 96vh; }}
dialog::backdrop {{ background: rgba(0,0,0,.75); }}
.lb {{ position: relative; display: inline-block; }}
.lb img {{ display: block; max-height: 86vh; max-width: 94vw; border-radius: 12px; }}
.lb-cap {{ color: #fff; font-size: 13px; margin-top: 8px; text-align: center; }}
.lb-close {{ position: absolute; top: 8px; right: 8px; border: 0; border-radius: 999px; width: 36px; height: 36px; font-size: 18px; cursor: pointer; background: rgba(0,0,0,.6); color: #fff; }}
@media (max-width: 640px) {{
  .issue {{ grid-template-columns: 80px 1fr; }}
  .err {{ grid-template-columns: 1fr; }} .shot.big {{ width: 160px; }}
  .bar-row {{ grid-template-columns: 1fr 60px; }} .bar-label {{ grid-column: 1 / -1; }}
}}
</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <div><h1>QA · Sección Offshore</h1>
  <div class="muted">App BTG Pactual (iPhone, controlado vía Duplicación del iPhone) · {esc(meta['started'][:10])} · {first_ts}–{last_ts} · run <code>{esc(meta['name'])}</code></div></div>
</header>
<nav class="toc" aria-label="Secciones">
  <a href="#resumen">Resumen</a><a href="#hallazgos">Hallazgos ({len(issues)})</a><a href="#errores">Errores ({len(errors)})</a>
  <a href="#idioma">Idioma</a><a href="#tiempos">Tiempos</a><a href="#flujos">Flujos ({len(flows)})</a><a href="#sin-efecto">Toques sin efecto</a><a href="#metodo">Metodología</a>
</nav>

<section id="resumen">
{kpis}
<div class="callout"><h3 style="margin-top:0">Hallazgos de severidad alta</h3><ol>{summary_list}</ol></div>
</section>

<section id="hallazgos">
<h2>Hallazgos</h2>
<div class="filters" role="group" aria-label="Filtrar hallazgos">
  <button data-sev="all" aria-pressed="true">Todos</button>
  <button data-sev="alta" aria-pressed="false">{SEV_ICON['alta']} Alta ({sev_count['alta']})</button>
  <button data-sev="media" aria-pressed="false">{SEV_ICON['media']} Media ({sev_count['media']})</button>
  <button data-sev="baja" aria-pressed="false">{SEV_ICON['baja']} Baja ({sev_count['baja']})</button>
  <select id="catf" aria-label="Categoría"><option value="all">Todas las categorías</option>{cats_opts}</select>
</div>
<div id="issues">{''.join(issue_cards)}</div>
</section>

<section id="errores">
<h2>Errores funcionales</h2>
<p class="muted">Pantallas donde la app falló: cargas que no terminan, gráficos no disponibles, reintentos que no funcionan y entradas que alteran el monto.</p>
{error_cards}
</section>

<section id="idioma">
<h2>Idioma y ortografía</h2>
<h3>Hallazgos confirmados</h3>
<ul class="callout">{i18n_issues}</ul>
<h3>Detección automática de textos en inglés o portugués (OCR) · {len(lang)} textos únicos</h3>
<p class="muted">Cada texto se marca en rojo sobre la captura. Los nombres propios de empresas y tickers se excluyen.</p>
<div class="table-scroll"><table><thead><tr><th>Captura</th><th>Texto</th><th>Flujos</th><th>Pasos</th></tr></thead><tbody>{''.join(lang_rows)}</tbody></table></div>
<h3>Palabras sin tilde (detección automática) · {len(accents)}</h3>
<div class="table-scroll"><table><thead><tr><th>Captura</th><th>Corrección</th><th>Textos donde aparece</th><th>Pantallas</th></tr></thead><tbody>{acc_rows}</tbody></table></div>
</section>

<section id="tiempos">
<h2>Tiempos de espera entre pantallas</h2>
<p class="muted">Tiempo desde el toque hasta que la pantalla deja de cambiar (3 capturas consecutivas iguales). Incluye unos 0,3 s de latencia de la Duplicación del iPhone. Las barras rayadas (⏳) son pantallas que seguían animando (skeleton o spinner) a los 25 s.</p>
<div class="chart" role="img" aria-label="Transiciones más lentas">
  <h3 style="margin-top:0">Transiciones más lentas (&gt; {SLOW:.0f} s)</h3>
  {bars}
  <div class="legend"><span><i style="background:var(--bar)"></i>tiempo hasta pantalla estable</span><span><i style="background:repeating-linear-gradient(135deg,var(--bar-timeout) 0 3px,transparent 3px 6px)"></i>no se estabilizó (carga infinita)</span></div>
</div>
<h3>Promedio por flujo</h3>
<div class="table-scroll"><table><thead><tr><th>Flujo</th><th>Promedio (s)</th><th>Transiciones</th></tr></thead><tbody>{flow_avg_rows}</tbody></table></div>
<details><summary class="muted" style="cursor:pointer;margin-top:12px">Ver todas las transiciones ({len(trans)})</summary>
<div class="table-scroll"><table><thead><tr><th>Paso</th><th>Flujo</th><th>Acción</th><th>Segundos</th><th></th></tr></thead><tbody>{t_rows}</tbody></table></div></details>
</section>

<section id="flujos">
<h2>Flujos (capturas paso a paso)</h2>
<p class="muted">Los flujos con hallazgos aparecen abiertos. El borde rojo marca los pasos con hallazgos y el recuadro rojo dentro de la captura marca los textos que no están en español.</p>
{''.join(flow_html)}
</section>

<section id="sin-efecto">
<h2>Toques sin efecto ({len(no_effect)})</h2>
<p class="muted">Acciones después de las cuales la pantalla quedó igual (comparación píxel a píxel). Pueden ser botones deshabilitados, áreas táctiles pequeñas o elementos que no responden.</p>
<ul class="callout">{no_effect_rows}</ul>
</section>

<section id="metodo">
<h2>Metodología y limitaciones</h2>
<ul class="callout">
<li>El iPhone se controló desde el Mac con la Duplicación del iPhone, con scripts propios: <code>tools/mirror</code> (captura, OCR con Apple Vision en español e inglés, toques y scroll) y <code>tools/qa.py</code> (pasos, tiempos y detecciones).</li>
<li>Por seguridad <b>no se confirmó ninguna operación</b>: las ventas llegaron hasta la pantalla «Confirmar» y no se tocaron «Cancelar» órdenes, transferencias ni abonos.</li>
<li>Los saltos en la numeración de pasos corresponden a capturas descartadas por errores del script (navegación), no de la app.</li>
<li>Las cuentas de origen/destino no tenían saldo, así que los flujos Transferir y Abonar se validaron solo hasta la validación de monto.</li>
<li>La detección de idioma es heurística (OCR + diccionario). Los hallazgos de la lista principal se verificaron visualmente en la captura.</li>
<li>Ejecutado fuera del horario de mercado (19:20–19:45 hora de Chile): algunos errores de gráficos/precios podrían depender del horario, pero igual deberían mostrar un estado coherente.</li>
</ul>
</section>
</div>

<div id="tip" role="tooltip"></div>
<dialog id="lb"><div class="lb"><img id="lb-img" alt=""><div id="lb-boxes"></div><button class="lb-close" aria-label="Cerrar">✕</button></div><div class="lb-cap" id="lb-cap"></div></dialog>
<script>
(function() {{
  var sev = 'all', cat = 'all';
  function apply() {{
    document.querySelectorAll('#issues .issue').forEach(function(el) {{
      el.style.display = ((sev === 'all' || el.dataset.sev === sev) && (cat === 'all' || el.dataset.cat === cat)) ? '' : 'none';
    }});
  }}
  document.querySelectorAll('.filters button').forEach(function(b) {{
    b.addEventListener('click', function() {{
      sev = b.dataset.sev;
      document.querySelectorAll('.filters button').forEach(function(x) {{ x.setAttribute('aria-pressed', x === b); }});
      apply();
    }});
  }});
  document.getElementById('catf').addEventListener('change', function(e) {{ cat = e.target.value; apply(); }});

  var lb = document.getElementById('lb'), img = document.getElementById('lb-img'),
      boxes = document.getElementById('lb-boxes'), cap = document.getElementById('lb-cap');
  document.addEventListener('click', function(e) {{
    var b = e.target.closest('.shot');
    if (!b) return;
    img.src = b.dataset.full; cap.textContent = b.dataset.cap; boxes.innerHTML = '';
    JSON.parse(b.dataset.boxes || '[]').forEach(function(r) {{
      var s = document.createElement('span'); s.className = 'box';
      s.style.cssText = 'left:' + r.x*100 + '%;top:' + r.y*100 + '%;width:' + r.w*100 + '%;height:' + r.h*100 + '%';
      boxes.appendChild(s);
    }});
    lb.showModal();
  }});
  lb.addEventListener('click', function(e) {{ if (e.target === lb || e.target.classList.contains('lb-close')) lb.close(); }});

  var tip = document.getElementById('tip');
  document.querySelectorAll('.bar-row').forEach(function(r) {{
    function show(x, y) {{ tip.textContent = r.dataset.tip; tip.style.display = 'block';
      tip.style.left = Math.min(x + 12, innerWidth - 330) + 'px'; tip.style.top = (y + 14) + 'px'; }}
    r.addEventListener('mousemove', function(e) {{ show(e.clientX, e.clientY); }});
    r.addEventListener('focus', function() {{ var b = r.getBoundingClientRect(); show(b.left, b.bottom); }});
    r.addEventListener('mouseleave', function() {{ tip.style.display = 'none'; }});
    r.addEventListener('blur', function() {{ tip.style.display = 'none'; }});
  }});
}})();
</script>
</body>
</html>"""
    out = os.path.join(rd, "reporte.html")
    open(out, "w").write(doc)
    return out, len(steps), len(issues)


if __name__ == "__main__":
    rd = sys.argv[1] if len(sys.argv) > 1 else qa.run_dir()
    out, n, m = build(rd)
    print(f"{out}  ({n} pasos, {m} hallazgos)")
