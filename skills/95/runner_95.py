#!/usr/bin/env python3
"""Runner autonomo del Protocolo 95.

Encadena ciclos CONSTRUCCION -> AUDITORIA -> GATE, escribe los artefactos del RUN
y solo pide humano cuando salta un freno.

Ejemplo:
python3 runner_95.py --run /abs/_95/20260821-mi-run --daemon
"""
from __future__ import annotations

import argparse, difflib, importlib.util, json, os, re, shlex, shutil, signal, subprocess, sys, tempfile, unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

VER_RE = re.compile(r"^VEREDICTO: (PASA|FALLA)$")
AUDIT_RE = re.compile(r"^C(\d+)_AUDIT\.md$")
GATE_KEYS = tuple(f"C{i}" for i in range(1, 11))
DEFAULT_GATE = "~/.claude/skills/95/gate_95.py"
DEFAULT_BARRIDO = "~/.claude/bin/barrido_refutados.py"
DEFAULT_PROMPTS = "~/.claude/skills/95/prompts"
DEFAULT_LOG = "~/.claude/memory/95_log.jsonl"
FRASES_CRITERIO = ("decision de diseno", "requiere decision", "requiere criterio", "el brief no especifica", "el brief no define", "no esta especificado en el brief", "admite dos lecturas", "elegir entre", "dos caminos", "hay que decidir", "falta definir", "exige definir", "solo el dueno", "solo aniol", "techo real", "cambio de alcance", "pivote", "contradice el brief", "reescribir desde cero")
RUNNER_ACTIVO: "Runner | None" = None

def ahora() -> str: return datetime.now().isoformat(timespec="seconds")
def ruta_abs(r: str | Path) -> str: return os.path.abspath(os.path.expanduser(str(r)))
def leer(r: str | Path) -> str:
    with open(r, "r", encoding="utf-8") as fh: return fh.read()
def escribir(r: str | Path, t: str) -> None:
    Path(r).parent.mkdir(parents=True, exist_ok=True)
    with open(r, "w", encoding="utf-8") as fh: fh.write(t)
def norm_txt(x: Any) -> str:
    raw = unicodedata.normalize("NFKD", str(x or ""))
    return re.sub(r"\s+", " ", "".join(c for c in raw if not unicodedata.combining(c)).lower()).strip()
def truthy(x: Any) -> bool:
    if isinstance(x, bool): return x
    if x in (None, "", [], {}): return False
    return norm_txt(x) not in {"false", "no", "0", "ninguno", "nada"} if isinstance(x, str) else bool(x)
def campo(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if d.get(k) not in (None, ""): return d.get(k)
    return ""

def cargar_gate(ruta_gate: str):
    ruta = ruta_abs(ruta_gate)
    if not os.path.exists(ruta): raise RuntimeError(f"no existe gate_95.py en {ruta}")
    spec = importlib.util.spec_from_file_location("gate_95_runtime", ruta)
    if spec is None or spec.loader is None: raise RuntimeError(f"no se pudo importar gate_95.py en {ruta}")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    if not hasattr(mod, "SEV_ALIAS") or not hasattr(mod, "extraer_primer_json"):
        raise RuntimeError("gate_95.py no expone SEV_ALIAS y extraer_primer_json")
    return mod

def normalizar_hallazgos(audit: dict[str, Any], gate_mod: Any) -> list[dict[str, Any]]:
    out = []
    for i, it in enumerate(audit.get("hallazgos") if isinstance(audit.get("hallazgos"), list) else [], 1):
        if not isinstance(it, dict): continue
        archivo, linea = it.get("archivo"), it.get("linea")
        donde = str(it.get("donde") or (f"{archivo}:{linea}" if archivo not in (None, "") and linea not in (None, "") else it.get("ubicacion") or archivo or ""))
        sev = gate_mod.SEV_ALIAS.get(norm_txt(campo(it, ("sev", "gravedad", "severidad"))), norm_txt(campo(it, ("sev", "gravedad", "severidad"))))
        out.append({"idx": i, "sev": sev, "que": str(campo(it, ("que", "descripcion", "problema", "title"))), "donde": donde, "arreglo": str(campo(it, ("arreglo", "accion", "fix", "correccion"))), "criterio": truthy(campo(it, ("criterio", "requiere_criterio", "decision_diseno"))), "criterio_pregunta": str(campo(it, ("criterio_pregunta", "pregunta")))})
    return out

def normalizar_correcciones(audit: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for it in audit.get("correcciones") if isinstance(audit.get("correcciones"), list) else []:
        if isinstance(it, dict): out.append({"hallazgo": str(campo(it, ("hallazgo_previo", "hallazgo"))), "estado": str(it.get("estado", "")).strip().upper(), "evidencia": str(it.get("evidencia", ""))})
    return out

def parse_audit_texto(texto: str, gate_mod: Any) -> dict[str, Any]:
    audit = gate_mod.extraer_primer_json(texto)
    audit["_veredicto_linea"] = texto.splitlines()[0] if texto.splitlines() else ""
    audit["_hallazgos_norm"] = normalizar_hallazgos(audit, gate_mod)
    audit["_correcciones_norm"] = normalizar_correcciones(audit)
    return audit
def parse_audit(ruta: str | Path, gate_mod: Any) -> dict[str, Any]: return parse_audit_texto(leer(ruta), gate_mod)
def primera_linea_valida(ruta: str | Path) -> bool:
    try:
        with open(ruta, "r", encoding="utf-8") as fh: return bool(VER_RE.match(fh.readline().rstrip("\n")))
    except FileNotFoundError: return False
def checks_false(audit: dict[str, Any]) -> list[str]:
    gate = audit.get("gate"); return [k for k in GATE_KEYS if isinstance(gate, dict) and gate.get(k) is False]
def conteo_hallazgos(hs: list[dict[str, Any]]) -> dict[str, int]:
    c = {"grave": 0, "medio": 0, "leve": 0}
    for h in hs:
        if h.get("sev") in c: c[h["sev"]] += 1
    return c
def score_audit(a: dict[str, Any]) -> Any: return a.get("score_recalculado", a.get("score", "-"))

def titulo_brief(linea: str) -> str:
    s = norm_txt(linea.strip().lstrip("#-*0123456789. )")); p = s.split(" ", 1)[0] if s else ""
    return {"tarea": "TAREA", "uso": "USO", "criterios": "CRITERIOS DE EXITO", "entregables": "ENTREGABLES", "supuesto": "SUPUESTO RIESGOSO"}.get(p, "")
def extraer_entregables(brief: str) -> list[str]:
    out, dentro = [], False
    for lin in brief.splitlines():
        tit, limpia = titulo_brief(lin), lin.strip()
        if tit == "ENTREGABLES": dentro = True; continue
        if dentro and tit: break
        if dentro and limpia.startswith("/"): out.append(limpia)
    return out
def extraer_bloques_brief(brief: str) -> dict[str, str]:
    bloques = {k: [] for k in ("TAREA", "USO", "CRITERIOS DE EXITO", "ENTREGABLES", "SUPUESTO RIESGOSO")}; actual = ""
    for lin in brief.splitlines():
        tit = titulo_brief(lin)
        if tit: actual = tit; continue
        if actual: bloques[actual].append(lin.rstrip())
    return {k: "\n".join(v).strip() for k, v in bloques.items()}
def criterios(bloques: dict[str, str]) -> list[str]: return [x.strip() for x in bloques.get("CRITERIOS DE EXITO", "").splitlines() if x.strip()]
def ancestro(entregables: list[str]) -> str: return os.path.commonpath([os.path.dirname(ruta_abs(x)) for x in entregables])
def dentro(ruta: str, base: str) -> bool:
    try: return os.path.commonpath([ruta_abs(ruta), ruta_abs(base)]) == ruta_abs(base)
    except ValueError: return False
def validar_target(target: str, entregables: list[str]) -> None:
    t, home = ruta_abs(target), ruta_abs(Path.home())
    if t in {"/", home}: raise RuntimeError(f"--target prohibido: {t}")
    if dentro(t, "~/.claude"): raise RuntimeError(f"--target cae dentro de ~/.claude: {t}")
    if set(Path(t).parts) & {"OPENCLOW PROJECTS", "Mare", "05_ADMINISTRATIVO_LEGAL"}: raise RuntimeError(f"--target cae dentro de ruta prohibida: {t}")
    fuera = [x for x in entregables if not dentro(x, t)]
    if fuera: raise RuntimeError("--target no contiene todos los entregables: " + ", ".join(fuera))
def autodetectar(run_dir: Path) -> int:
    n = 0
    for p in run_dir.iterdir():
        m = AUDIT_RE.match(p.name)
        if m and primera_linea_valida(p): n = max(n, int(m.group(1)))
    return n + 1
def medir(entregables: list[str]) -> tuple[dict[str, int], dict[str, int]]:
    ls, bs = {}, {}
    for r in entregables:
        try: data = Path(r).read_bytes()
        except FileNotFoundError: data = b""
        ls[r] = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0); bs[r] = len(data)
    return ls, bs
def crecimiento_pct(previo: int, actual: int) -> int: return round(100 * (actual - previo) / max(previo, 1))

def ordenar_hallazgos(hs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    orden = {"grave": 0, "medio": 1, "leve": 2}
    return sorted(hs, key=lambda h: (orden.get(str(h.get("sev")), 9), int(h.get("idx", 0))))
def elegir_punto0(hs: list[dict[str, Any]], checks: list[str]) -> dict[str, Any]:
    for sev in ("grave", "medio", "leve"):
        for h in hs:
            if h.get("sev") == sev: return {"tipo": "hallazgo", "hallazgo": h}
    return {"tipo": "check", "check": checks[0]} if checks else {"tipo": "inicial", "texto": "construccion inicial del BRIEF"}
def texto_punto0(p: dict[str, Any]) -> str:
    if p.get("tipo") == "hallazgo":
        h = p["hallazgo"]; return f"{str(h.get('sev')).upper()} en {h.get('donde')}: {h.get('que')}"
    return f"cerrar el primer check en false: {p.get('check')}" if p.get("tipo") == "check" else str(p.get("texto", "construccion inicial"))
def diferencial(hs: list[dict[str, Any]], p: dict[str, Any]) -> list[dict[str, Any]]:
    exc = p["hallazgo"].get("idx") if p.get("tipo") == "hallazgo" else None
    return [h for h in ordenar_hallazgos(hs) if h.get("idx") != exc]
def seccion(t: str, cuerpo: str | list[str]) -> str:
    return f"## {t}\n\n{chr(10).join(cuerpo).strip() if isinstance(cuerpo, list) else cuerpo.strip()}\n"
def rutas_lectura(entregables: list[str], run_dir: Path, ciclo: int) -> list[str]:
    out = list(entregables) + [str(run_dir / "BRIEF.md"), str(run_dir / "RUBRICA.md")]
    if (run_dir / "MEMORIA.md").exists(): out.append(str(run_dir / "MEMORIA.md"))
    if ciclo > 1 and (run_dir / f"C{ciclo-1}_AUDIT.md").exists(): out.append(str(run_dir / f"C{ciclo-1}_AUDIT.md"))
    return out

def generar_buildprompt(base: str, run_dir: Path, target: str, ciclo: int, bloques: dict[str, str], entregables: list[str], audit_prev: dict[str, Any] | None, gate_prev: dict[str, Any] | None, hist_prev: dict[str, Any] | None) -> str:
    partes = [base.rstrip(), "---", f"# CICLO {ciclo} · {'CONSTRUCCION INICIAL' if ciclo == 1 else 'CORRECCION DIFERENCIAL'}\n\nRUN: {run_dir}\nWORKDIR: {target}\nCICLO: {ciclo}\n", seccion("Archivos que lees completos antes de escribir", rutas_lectura(entregables, run_dir, ciclo))]
    if ciclo == 1:
        partes += [seccion(k, bloques.get(k, "")) for k in ("TAREA", "USO", "CRITERIOS DE EXITO", "ENTREGABLES")]
    else:
        audit_prev = audit_prev or {}; hs = audit_prev.get("_hallazgos_norm", []); ch = checks_false(audit_prev); c = conteo_hallazgos(hs); lineas = (hist_prev or {}).get("lineas", {}) or medir(entregables)[0]; crece = int((hist_prev or {}).get("crecimiento_pct", 0) or 0)
        partes.append(seccion("Estado medido del ciclo anterior", [f"Veredicto: {audit_prev.get('veredicto', audit_prev.get('_veredicto_linea', '-'))}", f"Score: {(gate_prev or {}).get('score_recalculado', (gate_prev or {}).get('score', score_audit(audit_prev)))}", "Checks en false: " + (", ".join(ch) if ch else "ninguno"), "Hallazgos: grave {grave}, medio {medio}, leve {leve}".format(**c), "Lineas por entregable: " + ("; ".join(f"{k}: {v}" for k, v in lineas.items()) if lineas else "sin medicion previa"), f"crecimiento_pct: {crece}"]))
        p0 = elegir_punto0(hs, ch); p0_txt = ["Eleccion deterministica: primer GRAVE en orden de aparicion; si no hay, primer MEDIO; si no hay, primer LEVE; si no hay hallazgos, primer check en false."]
        if p0.get("tipo") == "hallazgo":
            h = p0["hallazgo"]; p0_txt += [f"Severidad: {h.get('sev')}", f"Donde: {h.get('donde')}", f"Que: {h.get('que')}", f"Arreglo: {h.get('arreglo')}"]
        elif p0.get("tipo") == "check": p0_txt.append(f"Check: {p0.get('check')}")
        else: p0_txt.append("Sin hallazgos ni checks en false en el audit anterior.")
        partes.append(seccion("PUNTO 0", p0_txt))
        diff = diferencial(hs, p0)
        if diff: partes.append(seccion("DIFERENCIAL", [f"{i}. {h.get('sev').upper()} | {h.get('donde')}\nQue: {h.get('que')}\nArreglo: {h.get('arreglo')}" for i, h in enumerate(diff, 1)]))
        abiertas = [c for c in audit_prev.get("_correcciones_norm", []) if c.get("estado") == "ABIERTO"]
        if abiertas: partes.append(seccion("HALLAZGOS PREVIOS QUE SIGUEN ABIERTOS", [f"- {c['hallazgo']} | evidencia: {c['evidencia']}" for c in abiertas]))
        if crece > 0:
            antes = (hist_prev or {}).get("lineas_antes", {})
            crecidos = [f"- {r}: {a} lineas. Cierra por debajo de {a} lineas." for r, a in lineas.items() if int(antes.get(r, 0) or 0) > 0 and int(a) > int(antes.get(r, 0) or 0)]
            if crecidos: partes.append(seccion("RESTRICCION DE TAMANO", crecidos))
    partes.append(seccion("LO QUE NO TOCAS", "No se escribe fuera del TARGET. No se tocan ~/.claude/, _95/, OPENCLOW PROJECTS/, Mare/ ni 05_ADMINISTRATIVO_LEGAL/. El BRIEF y la RUBRICA estan congelados."))
    cierre = criterios(bloques) or ["Cumplir el BRIEF vigente de forma verificable leyendo los entregables."]
    partes.append(seccion("CRITERIO DE ACEPTACION", cierre + ["El Punto 0 debe quedar cerrado de forma comprobable leyendo el archivo."]))
    return "\n".join(partes).rstrip() + "\n"

def generar_contexto(run_dir: Path, ciclo: int, bloques: dict[str, str], audit_prev: dict[str, Any] | None) -> str:
    hs = (audit_prev or {}).get("_hallazgos_norm", []); p0 = elegir_punto0(hs, checks_false(audit_prev or {})); diff = diferencial(hs, p0)
    nv = (audit_prev or {}).get("no_verificado", []); nv = nv if isinstance(nv, list) else [str(nv)]
    cerradas = [c for c in (audit_prev or {}).get("_correcciones_norm", []) if c.get("estado") == "CERRADO"]
    partes = [f"# CONTEXT FACTUAL · CICLO {ciclo}\n", "QUE SE ELIGIO\nPunto 0: " + texto_punto0(p0) + ".\nDiferencial: " + ("; ".join(f"{h.get('sev')} en {h.get('donde')}: {h.get('que')}" for h in diff) if diff else "sin diferencial medido.") + "\n"]
    partes.append("SUPUESTOS\n" + "\n".join([bloques.get("SUPUESTO RIESGOSO", "sin supuesto riesgoso declarado").strip()] + [f"no_verificado heredado: {x}" for x in nv if str(x).strip()]) + "\n")
    partes.append("PENDIENTES\n" + "\n".join([str(x) for x in nv if str(x).strip()] or ["nada fuera del Punto 0 y diferencial declarados."]) + "\n")
    partes.append("RECHAZOS A RE-JUZGAR\n" + "\n".join([f"{c['hallazgo']} | evidencia: {c['evidencia']}" for c in cerradas] or ["nada cerrado por auditor anterior."]) + "\n")
    return "\n".join(partes).rstrip() + "\n"

def generar_auditprompt(base: str, run_dir: Path, ciclo: int, entregables: list[str], audit_prev: dict[str, Any] | None) -> str:
    rutas = [str(run_dir / "BRIEF.md"), str(run_dir / "RUBRICA.md"), str(run_dir / f"C{ciclo}_CONTEXT.md")] + entregables
    partes = [base.rstrip(), "---", "# AUDITORIA CIEGA · CICLO {0}\n\nLee completos, sin muestrear:\n{1}\n".format(ciclo, "\n".join(rutas))]
    if ciclo > 1:
        hs = (audit_prev or {}).get("_hallazgos_norm", [])
        partes.append(seccion("Hallazgos del ciclo anterior, verificalos uno a uno antes de buscar nuevos", ["Verificalos uno a uno antes de buscar nuevos. En correcciones marca CERRADO o ABIERTO con evidencia archivo:linea."] + [f"H{i} {h.get('sev')}, {h.get('que')}" for i, h in enumerate(hs, 1)]))
    partes.append(seccion("Campo extra obligatorio", 'en cada hallazgo de severidad GRAVE anade el campo "criterio": true o false, y si es true anade "criterio_pregunta" con la pregunta concreta que debe responder el dueno. Pon true SOLO si cerrar el hallazgo exige una decision de diseno del dueno: el BRIEF admite dos lecturas incompatibles, hay que elegir entre dos caminos ambos validos, falta un dato, asset o credencial que solo el dueno desbloquea, o el arreglo obliga a cambiar el alcance del BRIEF. Pon false si es una correccion mecanica que un constructor puede ejecutar sin preguntar.'))
    partes.append(seccion("Formato de salida", "Primera linea exactamente `VEREDICTO: PASA` o `VEREDICTO: FALLA`, despues un unico bloque JSON del esquema de la RUBRICA, con `veredicto` tambien dentro del JSON, `gate` con las diez claves `C1` a `C10`, `dimensiones` con `D1` a `D6` de 1 a 10, y `score` entero de 0 a 100 coherente con las dimensiones, nunca en escala de 0 a 10."))
    return "\n".join(partes).rstrip() + "\n"

def correcciones_abiertas(a: dict[str, Any]) -> list[str]: return [c.get("hallazgo", "") for c in a.get("_correcciones_norm", []) if c.get("estado") == "ABIERTO"]
def freno_criterio(a: dict[str, Any], prev: dict[str, Any] | None, heur: str) -> dict[str, Any] | None:
    graves = [h for h in a.get("_hallazgos_norm", []) if h.get("sev") == "grave"]; ds = []
    if truthy(a.get("requiere_criterio")): ds.append({"razon": "explicita", "hallazgo": graves[0] if graves else {}, "pregunta": str(a.get("requiere_criterio"))})
    ds += [{"razon": "explicita", "hallazgo": h, "pregunta": h.get("criterio_pregunta") or ""} for h in graves if h.get("criterio")]
    if prev:
        prev_graves = [h for h in prev.get("_hallazgos_norm", []) if h.get("sev") == "grave"]
        for h in graves:
            if any(difflib.SequenceMatcher(None, norm_txt(h.get("que")), norm_txt(v.get("que"))).ratio() >= 0.75 for v in prev_graves):
                ds.append({"razon": "persistencia", "hallazgo": h, "pregunta": ""})
        rep = sorted((set(map(norm_txt, correcciones_abiertas(a))) & set(map(norm_txt, correcciones_abiertas(prev)))) - {""})
        if rep: ds.append({"razon": "persistencia", "hallazgo": {"sev": "grave", "que": rep[0], "donde": "correcciones", "arreglo": "requiere decision del dueno"}, "pregunta": ""})
    if heur == "auto":
        frases = [norm_txt(x) for x in FRASES_CRITERIO]
        ds += [{"razon": "textual", "hallazgo": h, "pregunta": ""} for h in graves if any(f in norm_txt(str(h.get("que", "")) + " " + str(h.get("arreglo", ""))) for f in frases)]
    if not ds: return None
    h = ds[0].get("hallazgo") or {}; pregunta = ds[0].get("pregunta") or h.get("criterio_pregunta") or f"Que criterio debe aplicar el constructor para cerrar este hallazgo: {h.get('que', 'sin texto')}?"
    return {"razon": ds[0].get("razon"), "hallazgos": [d.get("hallazgo", {}) for d in ds], "pregunta": pregunta}

def leer_gate_json(run_dir: Path, ciclo: int) -> dict[str, Any] | None:
    try: return json.loads(leer(run_dir / f"C{ciclo}_GATE.json").strip().splitlines()[0])
    except Exception: return None
def estado_resultado(estado: str, no_auditado: bool) -> str: return "cerrado" if estado == "CERRADO" else ("no-auditado" if no_auditado or estado == "PARA_ERROR" else "parcial")
def fmt_lista(xs: list[Any]) -> str:
    ys = [str(x).strip() for x in xs if str(x).strip()]; return "; ".join(ys) if ys else "nada"
def comando_reanudar(args: argparse.Namespace, ciclo: int) -> str:
    pares = [("--run", args.run), ("--target", args.target), ("--umbral", args.umbral), ("--tope", args.tope), ("--max-min", args.max_min), ("--timeout-min", args.timeout_min), ("--modelo", args.modelo), ("--esfuerzo", args.esfuerzo), ("--desde", ciclo), ("--criterio-heuristica", args.criterio_heuristica), ("--gate", args.gate), ("--barrido", args.barrido), ("--prompts", args.prompts), ("--log", args.log)]
    cmd = [sys.executable, str(Path(__file__).resolve())] + [str(x) for par in pares for x in par]
    if not args.avisar: cmd.append("--sin-aviso")
    return " ".join(shlex.quote(x) for x in cmd)

def comprimir_memoria(slug: str, hist: list[dict[str, Any]], audit: dict[str, Any] | None, bloques: dict[str, str], ciclo: int) -> str:
    scores = "; ".join(f"C{h.get('ciclo')} {h.get('veredicto')} {h.get('score')}" for h in hist) or "sin ciclos auditados"; ult = hist[-1] if hist else {}
    abiertos = ([f"{h.get('sev')} {h.get('donde')}: {h.get('que')}" for h in audit.get("_hallazgos_norm", [])] + [f"correccion abierta: {c}" for c in correcciones_abiertas(audit)]) if audit else []
    nv = [str(x) for x in audit.get("no_verificado", [])] if audit and isinstance(audit.get("no_verificado"), list) else []
    secs = [("HECHOS", [f"- Serie de scores: {scores}.", f"- Checks en false del ultimo ciclo: {fmt_lista(ult.get('checks_false', []))}.", f"- Lineas ultimo ciclo: {ult.get('lineas', {})}, crecimiento {ult.get('crecimiento_pct', 0)}%."]), ("DECISIONES", [f"- Punto 0 elegido: {ult.get('punto0', 'construccion inicial')}."]), ("SUPUESTOS", [f"- {bloques.get('SUPUESTO RIESGOSO', 'sin supuesto riesgoso declarado')}."]), ("RIESGOS", [f"- no_verificado: {x}" for x in nv] or ["- Sin no_verificado registrado."]), ("PENDIENTES", [f"- {x}" for x in abiertos] or ["- nada"])]
    while True:
        lines = [f"# MEMORIA · RUN {slug} (comprimida tras C{ciclo})", ""]
        for t, items in secs: lines += [f"## {t}"] + items + [""]
        if len(lines) <= 40: return "\n".join(lines).rstrip() + "\n"
        cut = False
        for name in ("PENDIENTES", "RIESGOS", "SUPUESTOS", "DECISIONES", "HECHOS"):
            for i, (t, items) in enumerate(secs):
                if t == name and len(items) > 1: items.pop(); secs[i] = (t, items); cut = True; break
            if cut: break
        if not cut: return "\n".join(lines[:40]).rstrip() + "\n"

class Runner:
    def __init__(self, args: argparse.Namespace, gate_mod: Any):
        self.args, self.gate_mod = args, gate_mod; self.run_dir = Path(ruta_abs(args.run)); self.slug = self.run_dir.name
        self.brief = leer(self.run_dir / "BRIEF.md"); self.bloques = extraer_bloques_brief(self.brief); self.entregables = extraer_entregables(self.brief)
        self.target = ruta_abs(args.target or ancestro(self.entregables)); self.args.target = self.target; self.ciclo = args.desde or autodetectar(self.run_dir)
        self.cwd_limpio = Path(f"/private/tmp/95run-{self.slug}"); self.state_path = self.run_dir / "RUNNER_STATE.json"; self.pid_path = self.run_dir / "RUNNER.pid"; self.log_path = self.run_dir / "RUNNER.log"
        self.estado = self.cargar_estado(); self.inicio_ts = self.estado.get("iniciado") or ahora(); self.inicio_dt = datetime.fromisoformat(self.inicio_ts)
    def cargar_estado(self) -> dict[str, Any]:
        try: st = json.loads(leer(self.state_path)) if self.state_path.exists() else {}
        except json.JSONDecodeError: st = {}
        st.update({"run": self.slug, "run_dir": str(self.run_dir), "target": self.target, "umbral": self.args.umbral, "tope": self.args.tope, "ciclo_actual": self.ciclo, "estado": st.get("estado", "CORRIENDO"), "pid": os.getpid()})
        st.setdefault("iniciado", ahora()); st.setdefault("historial", []); return st
    def guardar(self, fase: str | None = None) -> None:
        if fase: self.estado["fase"] = fase
        self.estado["actualizado"] = ahora(); self.estado["pid"] = os.getpid(); escribir(self.state_path, json.dumps(self.estado, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    def escribir_pid(self) -> None:
        if self.pid_path.exists():
            try: pid = int(leer(self.pid_path).strip()); os.kill(pid, 0)
            except (ValueError, ProcessLookupError, FileNotFoundError): pass
            else:
                if pid == os.getpid(): return
                raise RuntimeError(f"ya hay un runner vivo para este RUN: PID {pid}")
        escribir(self.pid_path, str(os.getpid()) + "\n")
    def borrar_pid(self) -> None:
        try:
            if self.pid_path.exists() and leer(self.pid_path).strip() == str(os.getpid()): self.pid_path.unlink()
        except OSError: pass
    def preparar_cwd(self) -> None:
        self.cwd_limpio.mkdir(parents=True, exist_ok=True)
        if (self.cwd_limpio / ".codex").exists(): shutil.rmtree(self.cwd_limpio / ".codex")
    def presupuesto_agotado(self) -> bool: return (datetime.now() - self.inicio_dt).total_seconds() >= self.args.max_min * 60
    def audit(self, ciclo: int) -> dict[str, Any] | None:
        p = self.run_dir / f"C{ciclo}_AUDIT.md"; return parse_audit(p, self.gate_mod) if p.exists() else None
    def hist_previo(self) -> dict[str, Any] | None:
        return next((h for h in reversed(self.estado.get("historial", [])) if h.get("ciclo") == self.ciclo - 1), None)
    def prev_score_gate(self) -> str:
        g = leer_gate_json(self.run_dir, self.ciclo - 1) if self.ciclo > 1 else None
        return str(g.get("score_recalculado", g.get("score"))) if g and ("score_recalculado" in g or "score" in g) else "-"
    def generar_prompts(self, audit_prev: dict[str, Any] | None, gate_prev: dict[str, Any] | None) -> None:
        p = Path(ruta_abs(self.args.prompts)); build = generar_buildprompt(leer(p / "constructor.md"), self.run_dir, self.target, self.ciclo, self.bloques, self.entregables, audit_prev, gate_prev, self.hist_previo())
        escribir(self.run_dir / f"C{self.ciclo}_BUILDPROMPT.md", build); escribir(self.run_dir / f"C{self.ciclo}_CONTEXT.md", generar_contexto(self.run_dir, self.ciclo, self.bloques, audit_prev)); escribir(self.run_dir / f"C{self.ciclo}_AUDITPROMPT.md", generar_auditprompt(leer(p / "auditor.md"), self.run_dir, self.ciclo, self.entregables, audit_prev))
    def codex_constructor(self) -> list[str]:
        return ["codex", "exec", "--ignore-user-config", "-m", self.args.modelo, "-c", "mcp_servers={}", "-c", f"model_reasoning_effort={self.args.esfuerzo}", "--skip-git-repo-check", "-s", "workspace-write", "-C", str(self.cwd_limpio), "--add-dir", self.target, "-o", str(self.run_dir / f"C{self.ciclo}_BUILD.md"), "-"]
    def codex_auditor(self, salida: Path) -> list[str]:
        return ["codex", "exec", "--ignore-user-config", "-m", self.args.modelo, "-c", "mcp_servers={}", "-c", f"model_reasoning_effort={self.args.esfuerzo}", "--skip-git-repo-check", "-s", "read-only", "-C", str(self.cwd_limpio), "-o", str(salida), "-"]
    def correr_codex(self, cmd: list[str], stdin_path: Path, log_path: Path) -> int:
        try: res = subprocess.run(cmd, input=leer(stdin_path), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=self.args.timeout_min * 60)
        except subprocess.TimeoutExpired as e:
            out = e.stdout or ""; out = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
            escribir(log_path, out + f"\nTIMEOUT: codex exec excedio {self.args.timeout_min} minutos\n"); raise RuntimeError(f"timeout de codex exec en C{self.ciclo}")
        escribir(log_path, res.stdout or ""); return int(res.returncode)
    def ejecutar_constructor(self) -> None:
        rc = self.correr_codex(self.codex_constructor(), self.run_dir / f"C{self.ciclo}_BUILDPROMPT.md", self.run_dir / f"C{self.ciclo}_BUILDLOG.txt")
        if rc != 0:
            with open(self.run_dir / f"C{self.ciclo}_BUILDLOG.txt", "a", encoding="utf-8") as fh: fh.write(f"\nBUILD exit!=0: {rc}\n")
    def ejecutar_auditor(self) -> bool:
        tmp, retry, noaudit = self.cwd_limpio / f"C{self.ciclo}_AUDIT.md", self.run_dir / f"C{self.ciclo}_AUDITPROMPT_RETRY.md", self.run_dir / f"C{self.ciclo}_NOAUDIT"
        for p in (self.run_dir / f"C{self.ciclo}_AUDIT.md", noaudit, tmp, retry, self.run_dir / f"C{self.ciclo}_AUDITLOG_RETRY.txt"):
            try: p.unlink()
            except FileNotFoundError: pass
        rc = self.correr_codex(self.codex_auditor(tmp), self.run_dir / f"C{self.ciclo}_AUDITPROMPT.md", self.run_dir / f"C{self.ciclo}_AUDITLOG.txt")
        if rc != 0: escribir(noaudit, f"NO-AUDITADO {ahora()}: codex exec exit!=0, ver C{self.ciclo}_AUDITLOG.txt\n"); return False
        if not primera_linea_valida(tmp):
            escribir(retry, "Tu primer renglon DEBE ser exactamente VEREDICTO: PASA o VEREDICTO: FALLA\n\n" + leer(self.run_dir / f"C{self.ciclo}_AUDITPROMPT.md"))
            try: tmp.unlink()
            except FileNotFoundError: pass
            rc = self.correr_codex(self.codex_auditor(tmp), retry, self.run_dir / f"C{self.ciclo}_AUDITLOG_RETRY.txt")
            if rc != 0: escribir(noaudit, f"NO-AUDITADO {ahora()}: retry auditor exit!=0, ver C{self.ciclo}_AUDITLOG_RETRY.txt\n"); return False
        if not primera_linea_valida(tmp): escribir(noaudit, f"NO-AUDITADO {ahora()}: veredicto invalido tras 1 reintento\n"); return False
        try: noaudit.unlink()
        except FileNotFoundError: pass
        shutil.copyfile(tmp, self.run_dir / f"C{self.ciclo}_AUDIT.md"); return True
    def correr_barrido(self) -> int:
        res = subprocess.run(["python3", ruta_abs(self.args.barrido), self.target], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        escribir(self.run_dir / f"C{self.ciclo}_BARRIDO.txt", res.stdout or ""); return 1 if res.returncode == 0 else 0
    def correr_gate(self, barrido_ok: int) -> dict[str, Any]:
        cmd = ["python3", ruta_abs(self.args.gate), "--audit", str(self.run_dir / f"C{self.ciclo}_AUDIT.md"), "--run", self.slug, "--umbral", str(self.args.umbral), "--ciclo", str(self.ciclo), "--prev-score", self.prev_score_gate(), "--tope", str(self.args.tope), "--barrido-ok", str(barrido_ok), "--log", self.args.log]
        res = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE); escribir(self.run_dir / f"C{self.ciclo}_GATE.json", res.stdout or "")
        if res.returncode != 0: raise RuntimeError(f"gate_95.py salio con codigo {res.returncode}: {res.stderr.strip()}")
        try: return json.loads((res.stdout or "").strip().splitlines()[0])
        except Exception as e: raise RuntimeError("gate_95.py no devolvio JSON valido") from e
    def agregar_historial(self, gate: dict[str, Any], audit: dict[str, Any], antes: dict[str, int], despues: dict[str, int], crece: int) -> None:
        p0 = elegir_punto0(audit.get("_hallazgos_norm", []), checks_false(audit)); _, bytes_despues = medir(self.entregables)
        item = {"ciclo": self.ciclo, "ts": ahora(), "accion": gate.get("accion"), "score": gate.get("score_recalculado", gate.get("score")), "gate_pass": gate.get("gate_pass"), "veredicto": gate.get("veredicto"), "hallazgos": gate.get("hallazgos", conteo_hallazgos(audit.get("_hallazgos_norm", []))), "checks_false": checks_false(audit), "lineas": despues, "lineas_antes": antes, "bytes": bytes_despues, "crecimiento_pct": crece, "punto0": texto_punto0(p0)[:220], "motivo": gate.get("motivo", "")}
        self.estado["historial"] = [h for h in self.estado.get("historial", []) if h.get("ciclo") != self.ciclo] + [item]; self.estado["prev_score"] = item["score"]
    def freno_sin_punto0(self, audit_prev: dict[str, Any]) -> dict[str, Any] | None:
        """Audit sin hallazgos ni checks en false que aun asi no cruza el umbral: no hay nada que
        arreglar, hay algo que decidir. Mandar al constructor a ciegas solo infla y baja el score."""
        if audit_prev.get("_hallazgos_norm") or checks_false(audit_prev) or correcciones_abiertas(audit_prev): return None
        g = leer_gate_json(self.run_dir, self.ciclo - 1) or {}
        score = g.get("score_recalculado", g.get("score"))
        if not isinstance(score, (int, float)) or score >= self.args.umbral: return None
        return {"razon": "sin_punto0",
                "hallazgos": [{"sev": "-", "donde": f"C{self.ciclo - 1}_AUDIT.md", "que": f"El auditor no dejo ningun hallazgo ni check en false y aun asi el score {score} no cruza el umbral {self.args.umbral}.", "arreglo": "No hay correccion mecanica pendiente que atacar."}],
                "pregunta": f"El entregable no tiene defectos senalados y se queda en {score} contra un umbral de {self.args.umbral}. Bajas el umbral, cambias la rubrica, o das por bueno el resultado?"}
    def escribir_para_criterio(self, freno: dict[str, Any], audit_prev: dict[str, Any]) -> None:
        lines = [f"# PARA_CRITERIO · RUN {self.slug}", "", f"Ciclo detectado: C{self.ciclo - 1}", f"Score: {score_audit(audit_prev)}", f"Razon: {freno.get('razon')}", "", "## Hallazgos"]
        for h in freno.get("hallazgos", []): lines += [f"- Severidad: {h.get('sev', '')}", f"  Donde: {h.get('donde', '')}", f"  Que: {h.get('que', '')}", f"  Arreglo: {h.get('arreglo', '')}"]
        lines += ["", "## Pregunta concreta", str(freno.get("pregunta", "")), "", "## Estado del RUN", json.dumps(self.estado, ensure_ascii=False, sort_keys=True), "", "## Reanudar", comando_reanudar(self.args, self.ciclo)]
        escribir(self.run_dir / "PARA_CRITERIO.md", "\n".join(lines).rstrip() + "\n")
    def cierre(self, estado: str, motivo: str) -> None:
        self.estado["estado"] = estado; self.estado["motivo"] = motivo; self.guardar("cierre"); audit = self.audit(self.ciclo) or self.audit(self.ciclo - 1)
        abiertos = ([f"{h.get('sev')} {h.get('donde')}: {h.get('que')}" for h in audit.get("_hallazgos_norm", [])] + correcciones_abiertas(audit)) if audit else []
        no_ver = [str(x) for x in audit.get("no_verificado", [])] if audit and isinstance(audit.get("no_verificado"), list) else []
        ciclos = "; ".join(f"C{h.get('ciclo')} {h.get('veredicto')} {h.get('score')}" for h in self.estado.get("historial", [])) or "sin ciclos auditados"
        txt = "\n".join([f"RESULTADO: existe en {self.target} y estado {estado_resultado(estado, (self.run_dir / f'C{self.ciclo}_NOAUDIT').exists())}", f"CICLOS: {ciclos}", f"ABIERTO: {fmt_lista(abiertos)}", f"LIMITES DEL PASA: {fmt_lista(no_ver)}", f"SUPUESTOS VIVOS: {fmt_lista([self.bloques.get('SUPUESTO RIESGOSO', '')])}", f"RUN reanudable: {self.run_dir}", "", "MOTIVO DE PARADA", f"{estado}: {motivo}", "", "COMO REANUDAR", comando_reanudar(self.args, self.ciclo)])
        escribir(self.run_dir / "CIERRE.md", txt.rstrip() + "\n")
    def avisar(self, estado: str) -> None:
        if not self.args.avisar or shutil.which("osascript") is None: return
        try: subprocess.run(["osascript", "-e", f'display notification "Runner 95 detenido: {estado}" with title "Protocolo 95"'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception: pass
    def parar(self, estado: str, motivo: str, codigo: int) -> int:
        self.cierre(estado, motivo); self.avisar(estado); return codigo
    def run(self) -> int:
        self.escribir_pid(); self.preparar_cwd(); self.estado["estado"] = "CORRIENDO"; self.guardar("inicio")
        try:
            while True:
                self.estado["ciclo_actual"] = self.ciclo
                if (self.run_dir / "STOP").exists(): return self.parar("PARA_MANUAL", "STOP presente en el RUN", 3)
                if self.presupuesto_agotado(): return self.parar("PARA_PRESUPUESTO", "presupuesto de reloj agotado antes de lanzar constructor", 3)
                audit_prev = self.audit(self.ciclo - 1) if self.ciclo > 1 else None; audit_prev2 = self.audit(self.ciclo - 2) if self.ciclo > 2 else None
                if audit_prev:
                    fr = freno_criterio(audit_prev, audit_prev2, self.args.criterio_heuristica) or self.freno_sin_punto0(audit_prev)
                    if fr: self.estado["estado"] = "PARA_CRITERIO"; self.guardar("para_criterio"); self.escribir_para_criterio(fr, audit_prev); return self.parar("PARA_CRITERIO", f"freno de criterio por {fr.get('razon')}", 3)
                self.guardar("generando_prompts"); self.generar_prompts(audit_prev, leer_gate_json(self.run_dir, self.ciclo - 1) if self.ciclo > 1 else None)
                if self.args.dry_run:
                    escribir(self.run_dir / "MEMORIA.md", comprimir_memoria(self.slug, self.estado.get("historial", []), audit_prev, self.bloques, self.ciclo)); return self.parar("CORRIENDO", "dry-run: prompts, CONTEXT y MEMORIA generados sin codex ni gate", 0)
                antes, _ = medir(self.entregables); self.guardar("constructor"); self.ejecutar_constructor(); despues, _ = medir(self.entregables); crece = crecimiento_pct(sum(antes.values()), sum(despues.values()))
                self.guardar("auditor")
                if not self.ejecutar_auditor(): return self.parar("PARA_ERROR", "ciclo no auditado", 3)
                audit_actual = self.audit(self.ciclo)
                if audit_actual is None: return self.parar("PARA_ERROR", "audit no disponible tras auditor", 3)
                self.guardar("barrido"); barrido_ok = self.correr_barrido(); self.guardar("gate"); gate = self.correr_gate(barrido_ok)
                self.agregar_historial(gate, audit_actual, antes, despues, crece); self.guardar("post_gate"); accion, motivo = str(gate.get("accion")), str(gate.get("motivo", "sin motivo del gate"))
                if accion == "CERRAR": return self.parar("CERRADO", motivo, 0)
                if accion in {"PARA_SCORE_BAJA", "PARA_TOPE", "PARA_CONVERGENCIA"}: return self.parar(accion, motivo, 3)
                if accion != "SIGUE": return self.parar("PARA_ERROR", f"accion desconocida del gate: {accion}", 3)
                escribir(self.run_dir / "MEMORIA.md", comprimir_memoria(self.slug, self.estado.get("historial", []), audit_actual, self.bloques, self.ciclo)); self.guardar("sigue"); self.ciclo += 1
        finally: self.borrar_pid()

def validar_run(args: argparse.Namespace, check_prompts: bool = False) -> None:
    run_dir = Path(ruta_abs(args.run))
    if not run_dir.is_dir(): raise RuntimeError(f"--run no es un directorio: {run_dir}")
    if not (run_dir / "BRIEF.md").exists() or not (run_dir / "RUBRICA.md").exists(): raise RuntimeError("el RUN debe contener BRIEF.md y RUBRICA.md")
    ents = extraer_entregables(leer(run_dir / "BRIEF.md"))
    if not ents: raise RuntimeError("BRIEF.md no declara entregables absolutos en el bloque ENTREGABLES")
    validar_target(ruta_abs(args.target or ancestro(ents)), ents)
    if check_prompts:
        leer(Path(ruta_abs(args.prompts)) / "constructor.md"); leer(Path(ruta_abs(args.prompts)) / "auditor.md")
def pid_vivo(pid_path: Path) -> int | None:
    try: pid = int(leer(pid_path).strip()); os.kill(pid, 0); return pid
    except Exception: return None
def lanzar_daemon(args: argparse.Namespace) -> int:
    run_dir = Path(ruta_abs(args.run)); pid = pid_vivo(run_dir / "RUNNER.pid")
    if pid: print(f"Ya hay un runner vivo para este RUN: PID {pid}", file=sys.stderr); return 3
    argv = [sys.executable, str(Path(__file__).resolve())] + [x for x in sys.argv[1:] if x != "--daemon"]
    with open(run_dir / "RUNNER.log", "a", encoding="utf-8") as log: proc = subprocess.Popen(argv, start_new_session=True, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    escribir(run_dir / "RUNNER.pid", str(proc.pid) + "\n"); print(f"PID {proc.pid} LOG {run_dir / 'RUNNER.log'} STATE {run_dir / 'RUNNER_STATE.json'}"); return 0

def crear_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Runner autonomo del Protocolo 95.")
    p.add_argument("--run", help="Directorio absoluto del RUN con BRIEF.md y RUBRICA.md"); p.add_argument("--target", help="Directorio unico que el constructor puede escribir")
    p.add_argument("--umbral", type=int, default=95, help="Umbral pasado tal cual a gate_95.py"); p.add_argument("--tope", type=int, default=6, help="Numero de ciclo maximo inclusive")
    p.add_argument("--max-min", type=int, default=240, help="Presupuesto de reloj del RUN entero"); p.add_argument("--timeout-min", type=int, default=45, help="Timeout por llamada individual a codex exec")
    p.add_argument("--modelo", default="gpt-5.6-sol", help="Modelo pasado con -m a codex"); p.add_argument("--esfuerzo", default="xhigh", help="model_reasoning_effort de codex")
    p.add_argument("--desde", type=int, help="Ciclo por el que empezar"); p.add_argument("--daemon", action="store_true", help="Relanza desacoplado y sale"); p.add_argument("--dry-run", action="store_true", help="Genera prompts, CONTEXT y MEMORIA sin codex ni gate")
    p.add_argument("--criterio-heuristica", choices=("auto", "off"), default="auto", help="Capa textual de PARA_CRITERIO"); p.add_argument("--gate", default=DEFAULT_GATE, help="Ruta del juez gate_95.py")
    p.add_argument("--barrido", default=DEFAULT_BARRIDO, help="Ruta del barrido de refutados"); p.add_argument("--prompts", default=DEFAULT_PROMPTS, help="Directorio con constructor.md y auditor.md"); p.add_argument("--log", default=DEFAULT_LOG, help="JSONL pasado al gate con --log")
    aviso = p.add_mutually_exclusive_group(); aviso.add_argument("--avisar", dest="avisar", action="store_true", default=True, help="Notificacion macOS al parar"); aviso.add_argument("--sin-aviso", dest="avisar", action="store_false", help="No notificar al parar")
    p.add_argument("--selftest", action="store_true", help="Corre las pruebas internas y sale"); return p

def ok(nombre: str, cond: bool) -> bool: print(("OK " if cond else "FAIL ") + nombre); return cond
def selftest(args: argparse.Namespace) -> int:
    try: gm = cargar_gate(args.gate)
    except Exception: print("FAIL importar gate"); return 1
    casos = []
    norm = normalizar_hallazgos({"hallazgos": [{"sev": "high", "que": "uno", "donde": "a:1", "arreglo": "fix"}, {"gravedad": "media", "descripcion": "dos", "archivo": "/tmp/x.md", "linea": 7, "accion": "cambiar"}]}, gm)
    casos.append(ok("normalizacion hallazgos", norm[0]["sev"] == "grave" and norm[0]["donde"] == "a:1" and norm[0]["arreglo"] == "fix" and norm[1]["sev"] == "medio" and norm[1]["donde"] == "/tmp/x.md:7" and norm[1]["arreglo"] == "cambiar"))
    h = normalizar_hallazgos({"hallazgos": [{"sev": "medio", "que": "m"}, {"sev": "grave", "que": "g"}]}, gm); casos.append(ok("punto0 grave sobre medio", elegir_punto0(h, [])["hallazgo"]["que"] == "g")); casos.append(ok("punto0 check sin hallazgos", elegir_punto0([], ["C3", "C8"])["check"] == "C3"))
    h2 = normalizar_hallazgos({"hallazgos": [{"sev": "leve", "que": "l"}, {"sev": "grave", "que": "g"}, {"sev": "medio", "que": "m"}]}, gm); casos.append(ok("orden diferencial", [x["que"] for x in diferencial(h2, {"tipo": "check"})] == ["g", "m", "l"]))
    casos.append(ok("crecimiento previo cero", crecimiento_pct(0, 3) == 300)); casos.append(ok("crecimiento previo positivo", crecimiento_pct(100, 115) == 15))
    exp = parse_audit_texto('VEREDICTO: FALLA\n{"veredicto":"FALLA","hallazgos":[{"sev":"grave","que":"x","arreglo":"y","criterio":true,"criterio_pregunta":"Decidir?"}]}', gm); casos.append(ok("para_criterio explicita", freno_criterio(exp, None, "auto") is not None))
    a1 = parse_audit_texto('VEREDICTO: FALLA\n{"veredicto":"FALLA","hallazgos":[{"sev":"grave","que":"El modulo no valida el contrato principal","arreglo":"validar"}]}', gm); a2 = parse_audit_texto('VEREDICTO: FALLA\n{"veredicto":"FALLA","hallazgos":[{"sev":"grave","que":"El modulo no valida el contrato principal completo","arreglo":"validar"}]}', gm)
    casos.append(ok("para_criterio persistencia", freno_criterio(a2, a1, "auto") is not None))
    tex = parse_audit_texto('VEREDICTO: FALLA\n{"veredicto":"FALLA","hallazgos":[{"sev":"grave","que":"El BRIEF no define que camino elegir","arreglo":"requiere decision"}]}', gm); casos.append(ok("para_criterio textual auto", freno_criterio(tex, None, "auto") is not None)); casos.append(ok("para_criterio textual off", freno_criterio(tex, None, "off") is None))
    mec = parse_audit_texto('VEREDICTO: FALLA\n{"veredicto":"FALLA","hallazgos":[{"sev":"grave","que":"Falta crear el archivo de salida","arreglo":"Crear el archivo exacto"}]}', gm); casos.append(ok("no criterio mecanico", freno_criterio(mec, None, "auto") is None))
    with tempfile.TemporaryDirectory() as td:
        base = Path(td); run = base / "run"; target = base / "target"; run.mkdir(); target.mkdir(); (target / "a.md").write_text("", encoding="utf-8")
        brief = "TAREA\nX\nUSO\nY\nCRITERIOS DE EXITO\n1. Z\nENTREGABLES\n" + str(target / "a.md") + "\nSUPUESTO RIESGOSO\nR\n"; (run / "BRIEF.md").write_text(brief, encoding="utf-8"); (run / "RUBRICA.md").write_text("R\n", encoding="utf-8")
        gp = generar_buildprompt("BASE C\n", run, str(target), 1, extraer_bloques_brief(brief), [str(target / "a.md")], None, None, None); casos.append(ok("buildprompt criterio al final", gp.rstrip().split("## ")[-1].startswith("CRITERIO DE ACEPTACION")))
        hist = [{"ciclo": i, "veredicto": "FALLA", "score": 70 + i, "checks_false": ["C1"], "lineas": {"/x": i}, "crecimiento_pct": i, "punto0": "p" * 80} for i in range(1, 7)]
        casos.append(ok("memoria 40 lineas", len(comprimir_memoria("run", hist, mec, {"SUPUESTO RIESGOSO": "R"}, 6).splitlines()) <= 40))
    brief_real = "# BRIEF · RUN de forma real\n\nTAREA\nT\n\nUSO\nU\n\nCRITERIOS DE EXITO (verificables leyendo el archivo entregado)\n1. C\n\nENTREGABLES\n/Users/x/Desktop/AGENTE_v3/director-creativo.md\n/Users/x/Desktop/AGENTE_v3/CAMBIOS.md\n\nSUPUESTO RIESGOSO\nS\n"
    ents = extraer_entregables(brief_real)
    casos.append(ok("entregables brief real", len(ents) == 2 and ents[0].endswith("director-creativo.md") and ents[1].endswith("CAMBIOS.md")))
    try: validar_target(str(Path.home() / ".claude" / "x"), [str(Path.home() / ".claude" / "x" / "a.md")]); rechazo = False
    except RuntimeError: rechazo = True
    casos.append(ok("rechaza target claude", rechazo)); return 0 if all(casos) else 1

def manejar_senal(signum: int, _frame: Any) -> None:
    if RUNNER_ACTIVO is not None:
        RUNNER_ACTIVO.estado["estado"] = "PARA_MANUAL"; RUNNER_ACTIVO.estado["motivo"] = f"senal {signum}"; RUNNER_ACTIVO.guardar("senal"); RUNNER_ACTIVO.borrar_pid()
    raise SystemExit(3)
def main(argv: list[str] | None = None) -> int:
    global RUNNER_ACTIVO
    parser = crear_parser(); args = parser.parse_args(argv)
    if args.selftest: return selftest(args)
    if not args.run: parser.error("--run es obligatorio salvo con --selftest")
    try:
        gate_mod = cargar_gate(args.gate); validar_run(args, True)
        if args.daemon: return lanzar_daemon(args)
        runner = Runner(args, gate_mod); RUNNER_ACTIVO = runner; signal.signal(signal.SIGTERM, manejar_senal); signal.signal(signal.SIGINT, manejar_senal); return runner.run()
    except Exception as e:
        if RUNNER_ACTIVO is not None:
            try: return RUNNER_ACTIVO.parar("PARA_ERROR", str(e), 3)
            finally: RUNNER_ACTIVO.borrar_pid()
        print(f"PARA_ERROR: {e}", file=sys.stderr); return 3
if __name__ == "__main__": raise SystemExit(main())
