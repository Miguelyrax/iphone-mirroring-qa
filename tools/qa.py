#!/usr/bin/env python3
"""Runner de QA sobre iPhone Mirroring.

Cada paso: ejecuta una acción, espera a que la pantalla se estabilice (midiendo el tiempo),
guarda captura + OCR y lo registra en runs/<run>/steps.jsonl.

  qa.py start <run>
  qa.py step <flujo> "<descripción>" tap <nx> <ny>
  qa.py step <flujo> "<descripción>" tapt "<texto visible>" [n]   # toca el n-ésimo texto que coincida
  qa.py step <flujo> "<descripción>" swipe <nx1> <ny1> <nx2> <ny2>
  qa.py step <flujo> "<descripción>" scroll down|up [pixeles]          # rueda del mouse; por defecto 400
  qa.py step <flujo> "<descripción>" back                          # gesto volver (poco fiable: mejor tap en la flecha ←)
  qa.py step <flujo> "<descripción>" type "<texto>"
  qa.py step <flujo> "<descripción>" none                          # solo captura el estado actual
  qa.py issue <alta|media|baja> <categoria> "<descripción>" [paso]  # por defecto, el último paso
  qa.py screen                                                     # OCR de la pantalla actual sin registrar
"""
import json
import os
import re
import subprocess
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
MIRROR = os.path.join(TOOLS, "mirror")
CURRENT = os.path.join(TOOLS, ".current_run")

STABLE_FRAMES = 3       # capturas consecutivas iguales para considerar la pantalla estable
TIMEOUT = 25.0

# Regla de idioma: el inglés está permitido; solo se marca el portugués y las claves i18n sin resolver.
# Palabras portuguesas que no existen en español (incluye formas sin tilde, porque el OCR a veces las pierde;
# se excluyen las que sin tilde coinciden con español: patrimonio, transferencia, ate, agora, dados, erro).
PT_WORDS = set("""
tesouro outros outras outro outra limpar pesquisar brasileiro brasileira educacional
você voce não nao também tambem até então entao ajuda dúvidas duvidas perguntas frequentes
ação acao ações acoes aplicação aplicacao aplicações aplicacoes investimento investimentos investir
renda fixa variável variavel rendimento rentabilidade carteira fundos ativo ativos conta contas
resgate resgatar saque extrato transferência senha cadastro voltar avançar avancar fechar
carregando atualizar atualizado atualização atualizacao hoje ontem mês
patrimônio disponível disponivel indisponível indisponivel nenhum nenhuma mais
corretora corretagem taxa taxas ordem ordens venda quantidade preço preco preços precos
liquidação liquidacao cotação cotacao posição posicao posições posicoes
obrigado selecionar selecione informações informacoes aguarde sucesso
""".split())
NO_ACCENT = {x.split(":")[0]: x.split(":")[1] for x in """
liquidacion:liquidación operacion:operación operaciones:operaciones dias:días ordenes:órdenes orden:orden
informacion:información transaccion:transacción ejecucion:ejecución expiracion:expiración comision:comisión
numero:número codigo:código telefono:teléfono direccion:dirección pais:país credito:crédito debito:débito
deposito:depósito rapido:rápido ultimo:último ultimos:últimos valido:válido invalido:inválido tambien:también
aqui:aquí despues:después ningun:ningún seleccion:selección accion:acción cotizacion:cotización
posicion:posición sesion:sesión condicion:condición descripcion:descripción situacion:situación
inversion:inversión rentabilidad:rentabilidad periodo:período minimo:mínimo maximo:máximo electronico:electrónico
politica:política rescision:rescisión suscripcion:suscripción asignacion:asignación evolucion:evolución
distribucion:distribución categoria:categoría habiles:hábiles habil:hábil estrategia:estrategia unico:único publico:público
""".split() if x.split(":")[0] != x.split(":")[1]}
KEY_PATTERN = re.compile(r"^[a-z]+([._][a-zA-Z0-9]+){1,}$")   # claves i18n sin traducir: offshore.home.title


def run_dir():
    if not os.path.exists(CURRENT):
        sys.exit("No hay run activo: qa.py start <nombre>")
    return open(CURRENT).read().strip()


def mirror(*args):
    r = subprocess.run([MIRROR, *map(str, args)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"mirror {args[0]} falló: {r.stderr.strip()}")
    return r.stdout


def capture(path):
    mirror("shot", path)


def ocr(path):
    return json.loads(mirror("ocr", path))


def lang_findings(items):
    """Textos en portugués o claves i18n sin resolver. El inglés NO se marca (está permitido)."""
    found = []
    for it in items:
        t = it["text"].strip()
        if KEY_PATTERN.match(t):
            found.append({"text": t, "reason": "clave i18n sin traducir", **box(it)})
            continue
        pt = [w for w in re.findall(r"[A-Za-zÀ-ÿ']+", t) if w.lower() in PT_WORDS]
        if pt:
            found.append({"text": t, "reason": "portugués: " + ", ".join(pt), **box(it)})
    return found


def ui_findings(items):
    out = []
    for it in items:
        t = it["text"].strip()
        for w in re.findall(r"[A-Za-zñÑ]+", t):
            if w.lower() in NO_ACCENT:
                out.append({"text": t, "reason": f"falta tilde: {w} → {NO_ACCENT[w.lower()]}", **box(it)})
        if re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", t):
            out.append({"text": t, "reason": "fecha técnica ISO sin formatear", **box(it)})
        if (t.endswith("...") or t.endswith("…")) and re.search(r"[A-Za-z]", t[:-3]):
            out.append({"text": t, "reason": "texto truncado", **box(it)})
        if re.search(r"\b(null|undefined|NaN|\[object Object\]|Exception)\b", t):
            out.append({"text": t, "reason": "valor técnico visible", **box(it)})
        if re.search(r"\d{1,3}(,\d{3})+\.\d{2}\b", t):
            out.append({"text": t, "reason": "formato numérico en inglés (1,234.56)", **box(it)})
    return out


def box(it):
    return {k: round(it[k], 4) for k in ("x", "y", "w", "h")}


def load_steps(rd):
    p = os.path.join(rd, "steps.jsonl")
    if not os.path.exists(p):
        return []
    return [json.loads(l) for l in open(p) if l.strip()]


def find_text(items, needle, n=1):
    needle_l = needle.lower()
    matches = [it for it in items if it["text"].strip().lower() == needle_l] or \
              [it for it in items if needle_l in it["text"].lower()]
    matches.sort(key=lambda it: (round(it["y"], 2), it["x"]))
    if len(matches) < n:
        sys.exit(f"No encontré '{needle}' en pantalla. Textos: {[it['text'] for it in items]}")
    m = matches[n - 1]
    return m["x"] + m["w"] / 2, m["y"] + m["h"] / 2


def do_action(action, args, rd):
    tmp = os.path.join(rd, "_pre.png")
    if action == "tap":
        mirror("tap", args[0], args[1]); return f"tap({args[0]},{args[1]})"
    if action == "tapt":
        mirror("shot", tmp)
        x, y = find_text(ocr(tmp), args[0], int(args[1]) if len(args) > 1 else 1)
        mirror("tap", x, y); return f"tap '{args[0]}' ({x:.3f},{y:.3f})"
    if action == "swipe":
        mirror("swipe", *args); return "swipe"
    if action == "scroll":
        amount = int(args[1]) if len(args) > 1 else 400
        mirror("scroll", 0.5, 0.6, -amount if args[0] == "down" else amount)
        return f"scroll {args[0]}"
    if action == "back":
        mirror("swipe", 0.01, 0.5, 0.7, 0.5); return "gesto volver"
    if action == "type":
        mirror("type", args[0]); return f"type '{args[0]}'"
    if action == "none":
        return "captura"
    sys.exit(f"acción desconocida: {action}")


def cmd_step(flow, desc, action, args):
    rd = run_dir()
    steps = load_steps(rd)
    idx = len(steps) + 1
    pre = os.path.join(rd, "_pre.png")
    capture(pre)

    t0 = time.time()
    action_desc = do_action(action, args, rd)

    frames, stable_since, first_change, prev_t, still = 0, None, None, 0.0, 0
    final = os.path.join(rd, "shots", f"{idx:03d}.png")
    prev_img = os.path.join(rd, "_prev.png")
    while True:
        capture(final)
        now = time.time() - t0
        frames += 1
        if first_change is None and float(mirror("diff", pre, final)) > 0.002:
            first_change = now
        if frames > 1 and float(mirror("diff", prev_img, final)) <= 0.0004:
            still += 1
            if stable_since is None:
                stable_since = prev_t
            if still >= STABLE_FRAMES - 1 and (action == "none" or first_change is not None or now > 3.0):
                break
        else:
            still, stable_since = 0, None
        subprocess.run(["cp", final, prev_img])
        prev_t = now
        if now > TIMEOUT:
            break
        time.sleep(0.05)

    load_time = round(stable_since if stable_since is not None else now, 2)
    timed_out = now > TIMEOUT
    items = ocr(final)
    diff_ratio = float(mirror("diff", pre, final))
    changed = diff_ratio > 0.002

    step = {
        "idx": idx, "flow": flow, "desc": desc, "action": action_desc, "ts": time.strftime("%H:%M:%S"),
        "load_time": load_time, "first_change": round(first_change, 2) if first_change else None,
        "timed_out": timed_out, "changed": changed, "diff_ratio": diff_ratio, "frames": frames,
        "shot": f"shots/{idx:03d}.png", "ocr": items,
        "lang": lang_findings(items), "ui": ui_findings(items),
    }
    with open(os.path.join(rd, "steps.jsonl"), "a") as f:
        f.write(json.dumps(step, ensure_ascii=False) + "\n")

    flags = []
    if timed_out: flags.append(f"⚠ TIMEOUT >{TIMEOUT}s")
    if not changed and action != "none": flags.append("⚠ la pantalla NO cambió")
    if load_time > 3: flags.append(f"⚠ lento {load_time}s")
    print(f"#{idx} [{flow}] {desc} — {action_desc} — {load_time}s {' '.join(flags)}")
    print_screen(items)
    for e in step["lang"] + step["ui"]:
        print(f"  ! {e['reason']}: «{e['text']}»")


def print_screen(items):
    for it in sorted(items, key=lambda it: (round(it["y"], 2), it["x"])):
        print(f"  ({it['x'] + it['w'] / 2:.3f},{it['y'] + it['h'] / 2:.3f}) {it['text']}")


def cmd_issue(sev, cat, desc, step_idx=None):
    rd = run_dir()
    steps = load_steps(rd)
    ref = next((s for s in steps if s["idx"] == int(step_idx)), None) if step_idx else (steps[-1] if steps else None)
    rec = {"step": ref["idx"] if ref else None, "flow": ref["flow"] if ref else None,
           "severity": sev, "category": cat, "desc": desc, "ts": time.strftime("%H:%M:%S")}
    with open(os.path.join(rd, "issues.jsonl"), "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("issue registrado en paso", rec["step"])


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    if a[0] == "start":
        rd = os.path.join(ROOT, "runs", a[1])
        os.makedirs(os.path.join(rd, "shots"), exist_ok=True)
        open(CURRENT, "w").write(rd)
        json.dump({"name": a[1], "started": time.strftime("%Y-%m-%d %H:%M:%S")},
                  open(os.path.join(rd, "meta.json"), "w"))
        print("run:", rd)
    elif a[0] == "step":
        cmd_step(a[1], a[2], a[3], a[4:])
    elif a[0] == "issue":
        cmd_issue(a[1], a[2], a[3], a[4] if len(a) > 4 else None)
    elif a[0] == "screen":
        p = os.path.join(run_dir(), "_pre.png")
        mirror("shot", p)
        print_screen(ocr(p))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
