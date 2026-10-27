#!/usr/bin/env python3
"""Unico camino a codex exec para el ecosistema loop-infinito.

Construye el comando canonico (patron de runner_95.py lineas 295-297):
  codex exec --ignore-user-config -m gpt-5.5 -c mcp_servers={} \
    -c model_reasoning_effort=<effort> --skip-git-repo-check -s <sandbox> \
    -C <cwd> [--add-dir <dir>]* [--output-schema <schema>] -o <out> -
con el prompt por stdin.

No usa variables de entorno para pasar datos AL comando (sin secretos ni config via env
en el subprocess): el unico env var que este script lee es CODEX_BIN, para poder apuntar
a un binario distinto durante --selftest. El resto hereda el entorno del proceso padre tal
cual, sin manipularlo.

Uso:
  codex_exec.py --sandbox read-only|workspace-write --cwd DIR [--add-dir DIR]... \
      --prompt ARCHIVO --out ARCHIVO [--schema ARCHIVO] [--log ARCHIVO] \
      [--effort minimal|low|medium|high|xhigh] [--timeout-min N]
  codex_exec.py --smoke [--schema ARCHIVO] --out ARCHIVO
  codex_exec.py --selftest

Codigos de salida: 0 ok · 2 MEDICION_INVALIDA (schema) · 73 PARA_LOCK · 75 DORMIDO_CUOTA · 124 timeout.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

MODELO = "gpt-5.5"
LOCK_PATH = os.path.expanduser("~/.claude/codex_exec.lock")
CLAUDE_DIR = os.path.expanduser("~/.claude")
EFFORTS = ("minimal", "low", "medium", "high", "xhigh")
LOCK_TIMEOUT_SEG = 30 * 60
RIVAL_TIMEOUT_SEG = 30 * 60
RIVAL_POLL_SEG = 60
SMOKE_PROMPT = (
    "Esto es una prueba de conexion (smoke test), no una tarea real. Responde "
    "unicamente con un JSON de estas cuatro claves exactas y nada mas: "
    '{{"tipo_salida": "smoke", "ok": true, "nonce": "<repite el nonce de abajo>", '
    '"modelo": "<tu nombre de modelo>"}}.\n'
    "nonce: {nonce}\n"
)


# ---------- utilidades de rutas ----------

def absruta(r: str) -> str:
    return os.path.abspath(os.path.expanduser(str(r)))


def guardia_cwd(cwd: str) -> None:
    """El cwd de codex nunca puede vivir bajo ~/.claude (LIMITES_CONOCIDOS.md condicion 1)."""
    a = absruta(cwd)
    if a == CLAUDE_DIR or a.startswith(CLAUDE_DIR + os.sep):
        raise SystemExit(f"cwd rechazado: {a} vive bajo ~/.claude")


def nonce() -> str:
    return uuid.uuid4().hex[:8]


# ---------- lock global (una sola llamada codex viva) ----------

def hay_proceso_rival(patrones: list[str], propio_pid: int) -> bool:
    """True si algun proceso vivo (que no sea este) casa con alguno de los patrones."""
    for pat in patrones:
        try:
            r = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True, timeout=5)
        except Exception:
            continue
        pids = [int(x) for x in r.stdout.split() if x.strip().isdigit() and int(x) != propio_pid]
        if pids:
            return True
    return False


def esperar_turno(patrones: list[str], limite_seg: int = RIVAL_TIMEOUT_SEG) -> bool:
    """Cede ante runner_95.py o codex exec ya vivos. Devuelve False si se agoto el limite."""
    fin = time.monotonic() + limite_seg
    propio = os.getpid()
    while hay_proceso_rival(patrones, propio):
        if time.monotonic() >= fin:
            return False
        time.sleep(RIVAL_POLL_SEG)
    return True


def adquirir_lock(ruta_lock: str = LOCK_PATH, timeout_seg: int = LOCK_TIMEOUT_SEG):
    """Bloquea con fcntl.flock hasta timeout_seg. Devuelve el file handle abierto (mantenlo
    vivo mientras dure la llamada) o None si se agoto el tiempo."""
    Path(ruta_lock).parent.mkdir(parents=True, exist_ok=True)
    fh = open(ruta_lock, "a+")
    fin = time.monotonic() + timeout_seg
    while True:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except BlockingIOError:
            if time.monotonic() >= fin:
                fh.close()
                return None
            time.sleep(2)


def liberar_lock(fh) -> None:
    if fh is None:
        return
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


# ---------- comando canonico ----------

API_KEYS = {"type", "properties", "required", "additionalProperties", "enum", "const", "anyOf", "$ref", "$defs", "items", "description", "title"}


def _podar_estricto(node, es_props: bool = False):
    # la API rechaza minimum/maximum/pattern/minItems...; esas reglas las sigue aplicando el validador interno
    if isinstance(node, dict):
        if es_props:
            return {k: _podar_estricto(v) for k, v in node.items()}
        out = {}
        for k, v in node.items():
            if k in ("properties", "$defs"):
                out[k] = _podar_estricto(v, es_props=True)
            elif k in API_KEYS:
                out[k] = _podar_estricto(v)
        return out
    if isinstance(node, list):
        return [_podar_estricto(v) for v in node]
    return node


def schema_api(schema: str, tipo_salida: str | None) -> str:
    """La API solo ve la raiz del schema y en modo estricto exige exactamente sus claves, asi que
    por llamada se deriva un schema cuya raiz es el bloque $defs[tipo_salida] (con $defs para los $ref)."""
    if not tipo_salida:
        return absruta(schema)
    root = json.loads(Path(absruta(schema)).read_text(encoding="utf-8"))
    bloque = root.get("$defs", {}).get(tipo_salida)
    if not bloque:
        return absruta(schema)
    derivado = _podar_estricto({**bloque, "$defs": root.get("$defs", {})})
    destino = Path(absruta(schema)).parent / "api" / f"{tipo_salida}.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(derivado, ensure_ascii=False, indent=1), encoding="utf-8")
    return str(destino)


def construir_cmd(binario: str, sandbox: str, cwd: str, add_dirs: list[str],
                   schema: str | None, effort: str, out: str, tipo_salida: str | None = None) -> list[str]:
    cmd = [binario, "exec", "--ignore-user-config", "-m", MODELO,
           "-c", "mcp_servers={}", "-c", f"model_reasoning_effort={effort}",
           "--skip-git-repo-check", "-s", sandbox, "-C", absruta(cwd)]
    for d in add_dirs:
        cmd += ["--add-dir", absruta(d)]
    if schema:
        cmd += ["--output-schema", schema_api(schema, tipo_salida)]
    cmd += ["-o", absruta(out), "-"]
    return cmd


# ---------- deteccion de cuota agotada ----------

RE_HORA = re.compile(r"try again at (\d{1,2}):(\d{2})\s*([AP]M)", re.IGNORECASE)


def parsear_retry_at(texto: str, ahora_dt: datetime) -> datetime:
    """Extrae 'try again at H:MM AM/PM' del texto. Sin hora parseable, ahora + 30 min (JUICIO)."""
    m = RE_HORA.search(texto or "")
    if not m:
        return ahora_dt + timedelta(minutes=30)
    hora, minuto, ampm = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ampm == "PM" and hora != 12:
        hora += 12
    if ampm == "AM" and hora == 12:
        hora = 0
    candidato = ahora_dt.replace(hour=hora, minute=minuto, second=0, microsecond=0)
    if candidato <= ahora_dt:
        candidato += timedelta(days=1)
    return candidato


RE_CUOTA_LINEA = re.compile(r"^\s*(?:error:\s*)?(?:you'?ve hit your usage limit|usage limit reached|rate limit)", re.IGNORECASE)


def es_cuota_agotada(texto: str) -> bool:
    # Solo lineas propias de codex (al inicio de linea, con o sin prefijo ERROR:). El stdout
    # incluye el prompt entero, y FUENTES.txt puede citar "usage limit" como dato historico:
    # falso positivo real el 3-sep-2026 (mesa valida devuelta como 75).
    return any(RE_CUOTA_LINEA.search(l) for l in (texto or "").splitlines())


def escribir_espera_cuota(out: str, texto: str) -> None:
    ahora_dt = datetime.now()
    retry_at = parsear_retry_at(texto, ahora_dt)
    ruta = os.path.join(os.path.dirname(absruta(out)) or ".", "ESPERA_CUOTA.json")
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump({"retry_at": retry_at.isoformat(timespec="seconds"),
                    "motivo": "usage_limit_o_rate_limit", "texto": (texto or "")[-2000:]},
                   fh, ensure_ascii=False, indent=2)
        fh.write("\n")


# ---------- extraccion de tokens ----------

RE_TOKENS = re.compile(r"tokens used[:\s]+([\d,]+)", re.IGNORECASE)


def parsear_tokens(texto: str) -> int | None:
    """Ultima aparicion de 'tokens used: N' en el log."""
    matches = RE_TOKENS.findall(texto or "")
    if not matches:
        return None
    return int(matches[-1].replace(",", ""))


# ---------- validador de schema sin dependencias ----------

def _resolver(esquema: dict, root: dict) -> dict:
    if isinstance(esquema, dict) and "$ref" in esquema:
        ref = esquema["$ref"]
        if not ref.startswith("#/$defs/"):
            return {}
        return root.get("$defs", {}).get(ref.split("/")[-1], {})
    return esquema


def _validar_valor(valor, esquema: dict, root: dict, ruta: str) -> str | None:
    esquema = _resolver(esquema, root)
    tipo = esquema.get("type")

    if tipo == "object":
        if not isinstance(valor, dict):
            return f"{ruta} (se esperaba object)"
        for req in esquema.get("required", []):
            if req not in valor:
                return f"{ruta}.{req} (falta, requerido)"
        props = esquema.get("properties", {})
        if esquema.get("additionalProperties") is False:
            extra = [k for k in valor if k not in props]
            if extra:
                return f"{ruta} (propiedades no declaradas: {extra})"
        for k, v in valor.items():
            if k in props:
                err = _validar_valor(v, props[k], root, f"{ruta}.{k}")
                if err:
                    return err
        return None

    if tipo == "array":
        if not isinstance(valor, list):
            return f"{ruta} (se esperaba array)"
        if "minItems" in esquema and len(valor) < esquema["minItems"]:
            return f"{ruta} (minItems {esquema['minItems']}, trae {len(valor)})"
        if "maxItems" in esquema and len(valor) > esquema["maxItems"]:
            return f"{ruta} (maxItems {esquema['maxItems']}, trae {len(valor)})"
        items = esquema.get("items")
        if items:
            for i, item in enumerate(valor):
                err = _validar_valor(item, items, root, f"{ruta}[{i}]")
                if err:
                    return err
        return None

    if tipo == "string":
        if not isinstance(valor, str):
            return f"{ruta} (se esperaba string)"
        if "enum" in esquema and valor not in esquema["enum"]:
            return f"{ruta} (valor '{valor}' fuera de enum {esquema['enum']})"
        if "pattern" in esquema and not re.match(esquema["pattern"], valor):
            return f"{ruta} (no cumple pattern {esquema['pattern']})"
        if "maxLength" in esquema and len(valor) > esquema["maxLength"]:
            return f"{ruta} (maxLength {esquema['maxLength']})"
        return None

    if tipo in ("number", "integer"):
        if isinstance(valor, bool) or not isinstance(valor, (int, float)):
            return f"{ruta} (se esperaba {tipo})"
        if tipo == "integer" and float(valor) != int(valor):
            return f"{ruta} (se esperaba integer)"
        if "minimum" in esquema and valor < esquema["minimum"]:
            return f"{ruta} (valor {valor} bajo minimum {esquema['minimum']})"
        if "maximum" in esquema and valor > esquema["maximum"]:
            return f"{ruta} (valor {valor} sobre maximum {esquema['maximum']})"
        return None

    if tipo == "boolean":
        if not isinstance(valor, bool):
            return f"{ruta} (se esperaba boolean)"
        return None

    return None  # tipo no declarado: no se valida mas


def validar_schema(root: dict, data: dict) -> str | None:
    """Valida data contra root (nuestro schema con $defs y bloques por tipo_salida).
    Devuelve None si es valido, o el mensaje del campo culpable si no."""
    if "tipo_salida" not in data:
        return "tipo_salida (falta, requerido)"
    tipo = data["tipo_salida"]
    if tipo not in root.get("properties", {}).get("tipo_salida", {}).get("enum", []):
        return f"tipo_salida (valor '{tipo}' fuera de enum)"
    bloque = root.get("$defs", {}).get(tipo)
    if not bloque:
        return f"tipo_salida (sin bloque $defs.{tipo} en el schema)"
    return _validar_valor(data, bloque, root, tipo)


# ---------- ejecucion ----------

class DormidoCuota(Exception):
    pass


class ParaLock(Exception):
    pass


def ejecutar(*, sandbox: str, cwd: str, add_dirs: list[str], prompt_text: str, out: str,
             schema: str | None, effort: str, timeout_min: int, log: str | None,
             saltar_rival: bool = False, tipo_salida: str | None = None) -> int:
    """Corre codex exec una vez con el comando canonico. Devuelve el codigo de salida final
    (0 ok, 2 schema invalido, 75 cuota, 124 timeout). Lanza ParaLock si no consigue turno."""
    guardia_cwd(cwd)
    binario = os.environ.get("CODEX_BIN", "codex")
    cmd = construir_cmd(binario, sandbox, cwd, add_dirs, schema, effort, out, tipo_salida=tipo_salida)

    if not saltar_rival:
        if not esperar_turno(["runner_95.py", "codex exec"]):
            raise ParaLock("otro codex o runner_95 vivo mas de 30 min: PARA_LOCK")

    fh = adquirir_lock()
    if fh is None:
        raise ParaLock("lock de codex_exec.lock ocupado mas de 30 min: PARA_LOCK")
    try:
        Path(absruta(out)).parent.mkdir(parents=True, exist_ok=True)
        try:
            res = subprocess.run(cmd, input=prompt_text, text=True,
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=timeout_min * 60)
        except subprocess.TimeoutExpired as e:
            salida = e.stdout or ""
            salida = salida.decode("utf-8", "replace") if isinstance(salida, bytes) else salida
            if log:
                Path(log).write_text(salida + "\nTIMEOUT: codex exec excedio "
                                      f"{timeout_min} minutos\n", encoding="utf-8")
            return 124
        salida = res.stdout or ""
        if log:
            Path(log).write_text(salida, encoding="utf-8")

        tokens = parsear_tokens(salida)
        if tokens is not None:
            Path(str(out) + ".tokens").write_text(str(tokens) + "\n", encoding="utf-8")

        if es_cuota_agotada(salida):
            escribir_espera_cuota(out, salida)
            return 75

        if schema:
            try:
                data = json.loads(Path(absruta(out)).read_text(encoding="utf-8"))
            except Exception as e:
                sys.stderr.write(f"MEDICION_INVALIDA: salida no es JSON valido ({e})\n")
                return 2
            campo_culpable = validar_schema(json.loads(Path(absruta(schema)).read_text(encoding="utf-8")), data)
            if campo_culpable:
                sys.stderr.write(f"MEDICION_INVALIDA: {campo_culpable}\n")
                return 2
        return 0 if res.returncode == 0 else res.returncode
    finally:
        liberar_lock(fh)


# ---------- selftest ----------

STUB = '''#!/usr/bin/env python3
import sys, json

def buscar(argv, flag):
    return argv[argv.index(flag) + 1] if flag in argv else None

def main():
    argv = sys.argv[1:]
    out = buscar(argv, "-o")
    stdin = sys.stdin.read()
    caso = "normal"
    for linea in stdin.splitlines():
        if linea.startswith("STUB_CASE:"):
            caso = linea.split(":", 1)[1].strip()
            break
    if caso == "usage":
        print("Usage limit reached. try again at 6:12 PM")
        return 0
    if caso == "badschema":
        with open(out, "w", encoding="utf-8") as fh:
            json.dump({"tipo_salida": "medicion", "nonce": "deadbeef",
                       "variables": [{"id": "V1", "nombre": "x", "peso": 9, "valor": "alto",
                                     "confianza": "ALTA", "clase": "PAPEL",
                                     "evidencia": {"tipo": "juicio", "formula": "", "n": 0,
                                                   "fuente": "JUICIO", "comando": ""},
                                     "esfuerzo": 5, "techo": False, "control": True,
                                     "intestable": False, "nota": ""}] * 5,
                       "no_verificado": "", "regresiones": [], "comandos_corridos": []}, fh)
        print("tokens used: 42")
        return 0
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"tipo_salida": "smoke", "ok": True, "nonce": "cafebabe", "modelo": "stub"}, fh)
    print("tokens used: 123")
    return 0

if __name__ == "__main__":
    sys.exit(main())
'''


def selftest() -> int:
    fallos: list[str] = []

    def ok(nombre: str, cond: bool) -> None:
        print(("OK   " if cond else "FAIL ") + nombre)
        if not cond:
            fallos.append(nombre)

    base = Path(os.path.expanduser("~/.claude/skills/loop-infinito/_selftest"))
    base.mkdir(parents=True, exist_ok=True)
    stub_path = base / "codex_exec_stub.py"
    stub_path.write_text(STUB, encoding="utf-8")
    stub_path.chmod(0o755)
    os.environ["CODEX_BIN"] = str(stub_path)
    schema = json.loads((Path(__file__).resolve().parents[1] /
                          "skills/loop-infinito/schemas/medicion.schema.json").read_text(encoding="utf-8"))

    # parseo de tokens
    ok("parsea 'tokens used: 123'", parsear_tokens("algo\ntokens used: 123\nmas") == 123)
    ok("ultima aparicion de tokens manda", parsear_tokens("tokens used: 1\ntokens used: 999") == 999)

    # retry_at con hora parseable
    ahora_dt = datetime(2026, 9, 2, 12, 0, 0)
    r = parsear_retry_at("Usage limit reached. try again at 6:12 PM", ahora_dt)
    ok("retry_at parsea 6:12 PM", r.hour == 18 and r.minute == 12)
    r2 = parsear_retry_at("sin hora aqui", ahora_dt)
    ok("retry_at cae a +30 min sin hora", r2 == ahora_dt + timedelta(minutes=30))

    # validador de schema: variable con peso 9 (fuera de 1-5) y valor string ('alto')
    var_mala = {"id": "V1", "nombre": "x", "peso": 9, "valor": "alto",
                "confianza": "ALTA", "clase": "PAPEL",
                "evidencia": {"tipo": "juicio", "formula": "", "n": 0,
                              "fuente": "JUICIO", "comando": ""},
                "esfuerzo": 5, "techo": False, "control": True,
                "intestable": False, "nota": ""}
    malo = {"tipo_salida": "medicion", "nonce": "deadbeef",
            "variables": [var_mala] * 5,  # 5 items: pasa minItems, falla en el campo
            "no_verificado": "", "regresiones": [], "comandos_corridos": []}
    err = validar_schema(schema, malo)
    ok("schema detecta peso fuera de rango o valor mal tipado", bool(err) and ("peso" in err or "valor" in err))

    bueno = json.loads((Path(__file__).resolve().parents[1] /
                         "skills/loop-infinito/schemas/medicion.ejemplo.json").read_text(encoding="utf-8"))
    ok("schema acepta el ejemplo bueno", validar_schema(schema, bueno) is None)

    # SMOKE_PROMPT.format() no debe reventar por las llaves literales del JSON de ejemplo
    try:
        rendido = SMOKE_PROMPT.format(nonce="abcd1234")
        ok("SMOKE_PROMPT.format() no revienta con llaves literales", "abcd1234" in rendido)
    except (KeyError, IndexError) as e:
        ok(f"SMOKE_PROMPT.format() no revienta con llaves literales ({e})", False)

    # lock: adquirido y liberado, sin dejarlo colgado
    lock_prueba = str(base / "lock_prueba.lock")
    fh1 = adquirir_lock(lock_prueba, timeout_seg=5)
    ok("lock se adquiere", fh1 is not None)
    liberar_lock(fh1)
    fh2 = adquirir_lock(lock_prueba, timeout_seg=5)
    ok("lock liberado permite readquirir de inmediato", fh2 is not None)
    liberar_lock(fh2)

    # hay_proceso_rival: mecanismo generico probado con un proceso propio y controlado,
    # nunca contra 'codex exec' o 'runner_95.py' reales (podria haber uno vivo de otra sesion)
    marca = f"codex_exec_selftest_marker_{os.getpid()}"
    proc = subprocess.Popen(["sleep", "5"], env={**os.environ, "CODEX_EXEC_SELFTEST_MARK": marca})
    try:
        time.sleep(0.3)
        r = subprocess.run(["pgrep", "-f", "sleep 5"], capture_output=True, text=True)
        detectado = bool(r.stdout.strip())
        ok("hay_proceso_rival detecta un proceso vivo controlado",
           not detectado or hay_proceso_rival(["sleep 5"], os.getpid()))
    finally:
        proc.terminate()
        proc.wait(timeout=5)
    ok("hay_proceso_rival no detecta nada tras terminar", not hay_proceso_rival([marca], os.getpid()))

    # ejecutar() exige un --cwd fuera de ~/.claude (guardia_cwd); el stub ignora el cwd,
    # asi que basta un directorio de paso, creado y borrado dentro de este mismo selftest.
    import shutil
    import tempfile
    cwd_prueba = tempfile.mkdtemp(prefix="codex_exec_selftest_cwd_")

    # extremo a extremo: caso normal (tokens + schema smoke ok), via ejecutar()
    out1 = str(base / "out_normal.json")
    log1 = str(base / "out_normal.log")
    rc1 = ejecutar(sandbox="read-only", cwd=cwd_prueba, add_dirs=[], prompt_text="STUB_CASE:normal\n",
                    out=out1, schema=str(Path(__file__).resolve().parents[1] /
                                          "skills/loop-infinito/schemas/medicion.schema.json"),
                    effort="low", timeout_min=1, log=log1, saltar_rival=True)
    ok("ejecutar() caso normal sale 0", rc1 == 0)
    ok("ejecutar() caso normal escribe .tokens", Path(out1 + ".tokens").read_text().strip() == "123")

    # extremo a extremo: caso cuota agotada
    out2 = str(base / "out_usage.json")
    log2 = str(base / "out_usage.log")
    rc2 = ejecutar(sandbox="read-only", cwd=cwd_prueba, add_dirs=[], prompt_text="STUB_CASE:usage\n",
                    out=out2, schema=None, effort="low", timeout_min=1, log=log2, saltar_rival=True)
    ok("ejecutar() caso usage limit sale 75", rc2 == 75)
    espera = json.loads((base / "ESPERA_CUOTA.json").read_text(encoding="utf-8"))
    ok("ESPERA_CUOTA.json trae retry_at con hora parseada",
       espera.get("retry_at", "").endswith("18:12:00"))

    # extremo a extremo: caso schema invalido (peso 9, valor 'alto')
    out3 = str(base / "out_badschema.json")
    log3 = str(base / "out_badschema.log")
    rc3 = ejecutar(sandbox="read-only", cwd=cwd_prueba, add_dirs=[], prompt_text="STUB_CASE:badschema\n",
                    out=out3, schema=str(Path(__file__).resolve().parents[1] /
                                          "skills/loop-infinito/schemas/medicion.schema.json"),
                    effort="low", timeout_min=1, log=log3, saltar_rival=True)
    ok("ejecutar() caso schema invalido sale 2", rc3 == 2)

    # limpieza: nunca /tmp, todo bajo _selftest/ salvo el cwd de paso (se borra aqui)
    shutil.rmtree(cwd_prueba, ignore_errors=True)
    for p in (stub_path, base / "lock_prueba.lock", Path(out1), Path(out1 + ".tokens"), Path(log1),
              Path(out2), Path(log2), base / "ESPERA_CUOTA.json", Path(out3), Path(out3 + ".tokens"),
              Path(log3)):
        try:
            p.unlink()
        except FileNotFoundError:
            pass
    os.environ.pop("CODEX_BIN", None)

    _sch = str(Path(__file__).resolve().parents[1] / "skills" / "loop-infinito" / "schemas" / "medicion.schema.json")

    _der = json.loads(Path(schema_api(_sch, "smoke")).read_text(encoding="utf-8"))

    ok("schema_api(smoke): raiz exige ok y nonce", set(_der.get("required", [])) >= {"tipo_salida", "ok", "nonce"} and _der.get("additionalProperties") is False)

    ok("schema_api poda palabras no estrictas", "minimum" not in json.dumps(_der) and "pattern" not in json.dumps(_der))

    ok("schema_api(medicion) conserva $defs para $ref", "variable" in json.loads(Path(schema_api(_sch, "medicion")).read_text(encoding="utf-8")).get("$defs", {}))

    print("\n" + ("SELFTEST OK" if not fallos else f"SELFTEST FALLA: {fallos}"))
    return 0 if not fallos else 1


# ---------- smoke real ----------

def smoke(schema: str | None, out: str, cwd: str | None) -> int:
    nonce_val = nonce()
    cwd = cwd or os.getcwd()
    return ejecutar(sandbox="read-only", cwd=cwd, add_dirs=[],
                     prompt_text=SMOKE_PROMPT.format(nonce=nonce_val), out=out,
                     schema=schema, effort="low", timeout_min=5, log=str(out) + ".log", tipo_salida="smoke")


# ---------- CLI ----------

def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="unico camino a codex exec")
    p.add_argument("--sandbox", choices=("read-only", "workspace-write"))
    p.add_argument("--cwd")
    p.add_argument("--add-dir", action="append", default=[])
    p.add_argument("--schema")
    p.add_argument("--prompt")
    p.add_argument("--out")
    p.add_argument("--log")
    p.add_argument("--effort", choices=EFFORTS, default="xhigh")
    p.add_argument("--timeout-min", type=int, default=45)
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args(argv)

    if a.selftest:
        return selftest()

    if a.smoke:
        if not a.out:
            p.error("--smoke exige --out")
        return smoke(a.schema, a.out, a.cwd)

    if not (a.sandbox and a.cwd and a.prompt and a.out):
        p.error("--sandbox, --cwd, --prompt y --out son obligatorios fuera de --smoke/--selftest")

    prompt_text = Path(absruta(a.prompt)).read_text(encoding="utf-8")
    try:
        return ejecutar(sandbox=a.sandbox, cwd=a.cwd, add_dirs=a.add_dir, prompt_text=prompt_text,
                         out=a.out, schema=a.schema, effort=a.effort, timeout_min=a.timeout_min,
                         log=a.log)
    except ParaLock as e:
        sys.stderr.write(f"PARA_LOCK: {e}\n")
        return 73


if __name__ == "__main__":
    sys.exit(main())
