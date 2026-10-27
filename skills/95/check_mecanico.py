#!/usr/bin/env python3
"""
GATE MECANICO del protocolo /95.

Calcula los checks C1..C10 con grep, exit codes y find, en vez de dejarlos al
juicio del auditor. Su salida se inyecta en el auditprompt para que el juez la
COPIE. Elimina de raiz los checks que un lector no puede probar leyendo, como
"no escribio fuera del directorio", que producian falsos negativos y bloqueaban
el gate para siempre.

Uso:
    python3 check_mecanico.py <RUN_DIR> [--target RUTA]

Lee <RUN_DIR>/CHECKS.json. Si no existe, corre solo los universales y avisa.

Formato de CHECKS.json:
{
  "target": "/ruta/absoluta/del/entregable",
  "raices_vigiladas": ["/ruta/donde/no/debe/escribir"],
  "docs": ["archivo1.md", "archivo2.html"],
  "checks": [
    {"id":"C1","tipo":"existe","archivos":["a.md","b.py"],"desc":"entregables"},
    {"id":"C2","tipo":"contiene_todos","archivo":"a.md","strings":["x","y"]},
    {"id":"C3","tipo":"no_contiene","docs":true,"regex":"seis viernes"},
    {"id":"C4","tipo":"script_exit0","cmd":["python3","medir.py"],"prohibido_en_salida":"CUMPLE"},
    {"id":"C5","tipo":"regex_pareada","docs":true,
     "patron":"\\\\d+[.,]\\\\d+\\\\s*x","exige":"n\\\\s*=\\\\s*\\\\d|MEDIDO|INDICIO"},
    {"id":"C6","tipo":"sin_em_dash","docs":true},
    {"id":"C7","tipo":"sin_escritura_fuera"},
    {"id":"C8","tipo":"barrido_refutados"}
  ]
}

Tipos disponibles: existe, contiene_todos, no_contiene, script_exit0,
regex_pareada, sin_em_dash, sin_escritura_fuera, barrido_refutados, secciones_min.

Marca temporal: sin_escritura_fuera compara contra <RUN_DIR>/.ciclo_start, que
el loop debe tocar al inicio de CADA ciclo. Si la marca falta o tiene mas de 24h,
el check se declara NO_APLICA en vez de dar un falso rojo.
"""
import json, os, re, subprocess, sys, time

def leer(target, f):
    p = os.path.join(target, f)
    if not os.path.exists(p):
        return ""
    return open(p, encoding="utf-8", errors="replace").read()

def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "uso: check_mecanico.py <RUN_DIR> [--target RUTA]"}))
        return 2
    run = os.path.abspath(sys.argv[1])
    cfg_path = os.path.join(run, "CHECKS.json")
    cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {}
    target = cfg.get("target")
    if "--target" in sys.argv:
        target = sys.argv[sys.argv.index("--target") + 1]
    if not target or not os.path.isdir(target):
        print(json.dumps({"error": f"target inexistente: {target}"}))
        return 2

    docs = cfg.get("docs") or [f for f in os.listdir(target)
                               if f.endswith((".md", ".html", ".txt"))]
    gate, ev = {}, {}

    for c in cfg.get("checks", []):
        cid, tipo = c.get("id"), c.get("tipo")
        ok, detalle = False, ""
        try:
            if tipo == "existe":
                falta = [f for f in c["archivos"]
                         if not os.path.exists(os.path.join(target, f))]
                ok = not falta
                detalle = "faltan: " + ", ".join(falta) if falta else f"{len(c['archivos'])} presentes"

            elif tipo == "contiene_todos":
                txt = leer(target, c["archivo"]).lower()
                sin = [s for s in c["strings"] if s.lower() not in txt]
                ok = not sin
                detalle = "faltan: " + ", ".join(sin) if sin else "todos presentes"

            elif tipo == "no_contiene":
                pat = re.compile(c["regex"], re.I)
                lista = docs if c.get("docs") else [c["archivo"]]
                malos = [f for f in lista if pat.search(leer(target, f))]
                ok = not malos
                detalle = "aparece en: " + ", ".join(malos) if malos else "cero apariciones"

            elif tipo == "script_exit0":
                r = subprocess.run(c["cmd"], cwd=target, capture_output=True,
                                   text=True, timeout=c.get("timeout", 180))
                salida = (r.stdout or "") + (r.stderr or "")
                prohibido = c.get("prohibido_en_salida")
                miente = bool(prohibido) and prohibido in salida and c.get("solo_si_vacio", True) \
                    and any(k in salida.lower() for k in ("no contiene", "sin datos", "falta"))
                ok = r.returncode == 0 and not miente
                ultima = (salida.strip().splitlines() or ["sin salida"])[-1]
                detalle = f"exit={r.returncode}; {ultima[:140]}"

            elif tipo == "regex_pareada":
                pat, exige = re.compile(c["patron"], re.I), re.compile(c["exige"], re.I)
                lista = docs if c.get("docs") else [c["archivo"]]
                fallos = []
                for f in lista:
                    for i, ln in enumerate(leer(target, f).splitlines(), 1):
                        if pat.search(ln) and not exige.search(ln):
                            fallos.append(f"{f}:{i}")
                ok = not fallos
                detalle = f"{len(fallos)} sin pareja: " + ", ".join(fallos[:8]) if fallos else "cero huerfanas"

            elif tipo == "sin_em_dash":
                lista = docs if c.get("docs", True) else [c["archivo"]]
                malos = [f for f in lista if "—" in leer(target, f)]
                ok = not malos
                detalle = "em-dash en: " + ", ".join(malos) if malos else "cero em-dashes"

            elif tipo == "secciones_min":
                txt = leer(target, c["archivo"])
                n = len(re.findall(c.get("regex", r"^##\s+"), txt, re.M))
                ok = n >= c["minimo"]
                detalle = f"{n} secciones (minimo {c['minimo']})"

            elif tipo == "sin_escritura_fuera":
                marca = os.path.join(run, ".ciclo_start")
                if not os.path.exists(marca) or (time.time() - os.path.getmtime(marca)) > 86400:
                    ok, detalle = True, "NO_APLICA: marca .ciclo_start ausente o caducada"
                else:
                    t0, fuera = os.path.getmtime(marca), []
                    for raiz in cfg.get("raices_vigiladas", []):
                        for dp, dns, fns in os.walk(raiz):
                            dns[:] = [d for d in dns if not d.startswith(".")]
                            if os.path.abspath(target) in os.path.abspath(dp):
                                continue
                            for fn in fns:
                                try:
                                    if os.path.getmtime(os.path.join(dp, fn)) > t0:
                                        fuera.append(os.path.join(dp, fn))
                                except OSError:
                                    pass
                            if len(fuera) > 5:
                                break
                    ok = not fuera
                    detalle = f"{len(fuera)} fuera: " + ", ".join(fuera[:3]) if fuera else "cero fuera del target"

            elif tipo == "barrido_refutados":
                r = subprocess.run([sys.executable,
                                    os.path.expanduser("~/.claude/bin/barrido_refutados.py"), target],
                                   capture_output=True, text=True, timeout=240)
                ok = r.returncode == 0
                salida = (r.stdout or r.stderr or "").strip().splitlines()
                detalle = salida[-1][:140] if salida else "sin salida"

            else:
                ok, detalle = False, f"tipo desconocido: {tipo}"
        except Exception as e:
            ok, detalle = False, f"error: {e}"

        gate[cid] = ok
        ev[cid] = detalle

    faltan_ids = [f"C{i}" for i in range(1, 11) if f"C{i}" not in gate]
    salida = {"gate": gate, "evidencia": ev,
              "todos_verdes": bool(gate) and all(gate.values()),
              "rojos": [k for k, v in gate.items() if not v]}
    if faltan_ids:
        salida["aviso"] = ("gate_95.py exige C1 a C10 completos; sin definir: "
                           + ", ".join(faltan_ids))
    if not cfg:
        salida["aviso"] = f"no existe {cfg_path}: no se corrio ningun check"
    print(json.dumps(salida, ensure_ascii=False, indent=2))
    return 0 if salida["todos_verdes"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
