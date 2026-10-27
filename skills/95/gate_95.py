#!/usr/bin/env python3
"""Motor de gate y score para el Protocolo 95."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple


PESOS = {"D1": 3, "D2": 3, "D3": 3, "D4": 2, "D5": 2, "D6": 2}
GATE_KEYS = tuple(f"C{i}" for i in range(1, int(os.environ.get("GATE_N", "10")) + 1))  # GATE_N: nº de checks del RUN (por defecto 10)
VEREDICTO_LINEA_RE = re.compile(r"^VEREDICTO: (PASA|FALLA)$")
DEFAULT_LOG = "~/.claude/memory/95_log.jsonl"


def extraer_primer_json(texto: str) -> Dict[str, Any]:
    """Extrae el primer objeto JSON balanceado dentro de un texto."""
    inicio = texto.find("{")
    if inicio == -1:
        raise ValueError("no se encontro un objeto JSON")

    profundidad = 0
    en_string = False
    escape = False

    for idx in range(inicio, len(texto)):
        ch = texto[idx]
        if en_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                en_string = False
            continue

        if ch == '"':
            en_string = True
        elif ch == "{":
            profundidad += 1
        elif ch == "}":
            profundidad -= 1
            if profundidad == 0:
                bloque = texto[inicio : idx + 1]
                return json.loads(bloque)

    raise ValueError("objeto JSON incompleto o no balanceado")


def parsear_audit(contenido: str) -> Dict[str, Any]:
    audit = extraer_primer_json(contenido)
    lineas = contenido.splitlines()
    match = VEREDICTO_LINEA_RE.match(lineas[0] if lineas else "")
    audit["_veredicto_linea"] = match.group(1) if match else ""
    return audit


def leer_audit(ruta: str) -> Dict[str, Any]:
    if ruta == "-":
        contenido = sys.stdin.read()
    else:
        with open(ruta, "r", encoding="utf-8") as fh:
            contenido = fh.read()
    return parsear_audit(contenido)


def normalizar_numero(valor: Any, defecto: float = 0.0) -> float:
    try:
        return float(valor)
    except (TypeError, ValueError):
        return defecto


def normalizar_score(valor: Any) -> int:
    score = round(normalizar_numero(valor, 0.0))
    return max(0, min(100, int(score)))


def score_desde_dimensiones(dimensiones: Any) -> int:
    if not isinstance(dimensiones, dict):
        dimensiones = {}
    total = 0.0
    peso_total = 0
    for clave, peso in PESOS.items():
        nota = normalizar_numero(dimensiones.get(clave), 0.0)
        nota = max(0.0, min(10.0, nota))
        total += peso * nota
        peso_total += peso
    return normalizar_score(100 * total / (peso_total * 10))


SEV_ALIAS = {
    "grave": "grave", "graves": "grave", "critico": "grave", "critical": "grave",
    "high": "grave", "alto": "grave", "alta": "grave", "blocker": "grave",
    "medio": "medio", "media": "medio", "medium": "medio", "moderado": "medio", "mid": "medio",
    "leve": "leve", "menor": "leve", "minor": "leve", "low": "leve", "bajo": "leve", "baja": "leve",
}


def contar_hallazgos(hallazgos: Any) -> Dict[str, int]:
    conteo = {"grave": 0, "medio": 0, "leve": 0}
    if not isinstance(hallazgos, list):
        return conteo
    for item in hallazgos:
        if not isinstance(item, dict):
            continue
        # acepta la clave 'sev' o 'gravedad', en cualquier idioma/caso
        raw = item.get("sev")
        if raw in (None, ""):
            raw = item.get("gravedad")
        clave = SEV_ALIAS.get(str(raw).strip().lower())
        if clave:
            conteo[clave] += 1
    return conteo


def hay_correccion_abierta(correcciones: Any) -> bool:
    return isinstance(correcciones, list) and any(
        isinstance(item, dict) and str(item.get("estado", "")).strip().upper() == "ABIERTO"
        for item in correcciones
    )


def leer_veredicto(valor: Any) -> str:
    if isinstance(valor, str) and valor in {"PASA", "FALLA"}:
        return valor
    return ""


def gate_todo_true(gate: Any) -> bool:
    if not isinstance(gate, dict):
        return False
    return (
        all(gate.get(clave) is True for clave in GATE_KEYS)
        and all(valor is True for valor in gate.values())
    )


def evaluar_senales(audit: Dict[str, Any], hallazgos: Dict[str, int]) -> Tuple[bool, bool, Dict[str, bool], str, bool]:
    veredicto_auditor = leer_veredicto(audit.get("veredicto"))
    veredicto_linea = leer_veredicto(audit.get("_veredicto_linea"))
    mismatch_linea = veredicto_linea == "" or veredicto_linea != veredicto_auditor
    hallazgos_raw = audit.get("hallazgos")
    senales = {
        "veredicto": veredicto_auditor == "PASA",
        "gate": gate_todo_true(audit.get("gate")),
        "hallazgos": (
            isinstance(hallazgos_raw, list)
            and hallazgos["grave"] == 0
            and hallazgos["medio"] < 3
        ),
    }
    inconsistente = veredicto_auditor == "" or mismatch_linea or len(set(senales.values())) != 1
    gate_pass = (not inconsistente) and all(senales.values())
    return gate_pass, inconsistente, senales, (veredicto_auditor or "INVALIDO"), mismatch_linea


def calcular_score(audit: Dict[str, Any], avisos: list[str]) -> Tuple[int, Optional[int], Optional[int]]:
    score_declarado = normalizar_score(audit.get("score")) if "score" in audit else None
    score_recalculado = score_desde_dimensiones(audit.get("dimensiones"))
    if score_declarado is not None and abs(score_declarado - score_recalculado) > 1:
        avisos.append("score_discrepancia")
    return score_recalculado, score_declarado, score_recalculado


def leer_historial_scores(ruta: str, run: str, ciclo_actual: int) -> list[int]:
    destino = os.path.expanduser(ruta)
    if not os.path.exists(destino):
        return []

    scores: list[int] = []
    with open(destino, "r", encoding="utf-8") as fh:
        for linea in fh:
            try:
                item = json.loads(linea)
                ciclo_log = int(item.get("ciclo"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if item.get("run") != run or ciclo_log >= ciclo_actual or "score" not in item:
                continue
            scores.append(normalizar_score(item.get("score")))
    return scores


def deltas_convergencia(score: int, historial_scores: list[int]) -> Optional[Tuple[int, int]]:
    if len(historial_scores) < 2:
        return None
    penultimo, ultimo = historial_scores[-2], historial_scores[-1]
    return score - ultimo, ultimo - penultimo


def estado_archivo(ruta: str) -> Optional[Tuple[int, int]]:
    try:
        stat = os.stat(os.path.expanduser(ruta))
    except FileNotFoundError:
        return None
    return stat.st_size, stat.st_mtime_ns


def parse_prev_score(valor: str) -> Optional[int]:
    if valor == "-":
        return None
    return normalizar_score(valor)


def evaluar(
    audit: Dict[str, Any],
    umbral: int,
    ciclo: int,
    prev_score: Optional[int],
    tope: int,
    historial_scores: Optional[list[int]] = None,
    barrido_ok: Optional[int] = None,
) -> Dict[str, Any]:
    avisos: list[str] = []
    hallazgos = contar_hallazgos(audit.get("hallazgos"))
    correccion_abierta = hay_correccion_abierta(audit.get("correcciones"))
    gate_pass, inconsistente, senales, veredicto_auditor, mismatch_linea = evaluar_senales(audit, hallazgos)
    if correccion_abierta:
        gate_pass = False
        avisos.append("correccion_abierta")
    if mismatch_linea:
        avisos.append("veredicto_linea_vs_json_mismatch")
    elif inconsistente:
        avisos.append("inconsistencia_auditor")

    score, score_declarado, score_recalculado = calcular_score(audit, avisos)
    score_cierra = score >= umbral

    if not gate_pass:
        score = min(score, 94)

    veredicto = "PASA" if gate_pass else "FALLA"
    deltas = deltas_convergencia(score, historial_scores or [])
    converge = deltas is not None and all(delta < 5 for delta in deltas)
    if gate_pass and score_cierra and barrido_ok != 1:
        avisos.append("barrido_no_verificado" if barrido_ok is None else "barrido_refutados_no_cero")

    # Precedencia unica de decision:
    # 1. CERRAR - solo si gate_pass True, score>=umbral, barrido_ok=1 y sin correcciones ABIERTAS.
    # 2. PARA_SCORE_BAJA - el score real recalculado sin capar bajo respecto al ciclo anterior.
    # 3. PARA_TOPE - ciclo>=tope domina cualquier SIGUE.
    # 4. PARA_CONVERGENCIA - dos deltas consecutivos <5 leidos del historial.
    # 5. SIGUE - con avisos como correccion_abierta o barrido_refutados_no_cero.
    if gate_pass and score_cierra and barrido_ok == 1 and not correccion_abierta:
        accion = "CERRAR"
        motivo = "gate PASA, score cruza el umbral y barrido_refutados cero"
    elif prev_score is not None and score_recalculado < prev_score:
        accion = "PARA_SCORE_BAJA"
        motivo = "el score bajo respecto al ciclo anterior"
    elif ciclo >= tope:
        accion = "PARA_TOPE"
        motivo = "el ciclo alcanzo el tope declarado"
    elif converge:
        accion = "PARA_CONVERGENCIA"
        motivo = "dos ciclos consecutivos sin mejora >=5 puntos"
    else:
        accion = "SIGUE"
        if correccion_abierta:
            motivo = "correccion_abierta"
        elif gate_pass and score_cierra and barrido_ok == 0:
            motivo = "barrido_refutados_no_cero"
        elif gate_pass and score_cierra:
            motivo = "barrido_no_verificado"
        elif mismatch_linea:
            motivo = "veredicto_linea_vs_json_mismatch"
        elif inconsistente:
            motivo = "inconsistencia_auditor"
        else:
            motivo = "no cruza umbral ni activa frenos"
    motivos = [motivo] + [aviso for aviso in avisos if aviso != motivo]

    return {
        "accion": accion,
        "score": score,
        "gate_pass": gate_pass,
        "veredicto": veredicto,
        "veredicto_auditor": veredicto_auditor,
        "motivo": motivo,
        "motivos": motivos,
        "avisos": avisos,
        "hallazgos": hallazgos,
        "senales": senales,
        "score_declarado": score_declarado,
        "score_recalculado": score_recalculado,
        "deltas_convergencia": list(deltas) if deltas is not None else None,
    }


def escribir_log(
    ruta: str,
    run: str,
    ciclo: int,
    umbral: int,
    prev_score: Optional[int],
    resultado: Dict[str, Any],
) -> None:
    destino = os.path.expanduser(ruta)
    directorio = os.path.dirname(destino)
    if directorio:
        os.makedirs(directorio, exist_ok=True)
    linea = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "run": run,
        "ciclo": ciclo,
        "umbral": umbral,
        "score": resultado["score"],
        "prev_score": prev_score,
        "gate_pass": resultado["gate_pass"],
        "veredicto": resultado["veredicto"],
        "veredicto_auditor": resultado["veredicto_auditor"],
        "accion": resultado["accion"],
        "motivo": resultado["motivo"],
        "motivos": resultado["motivos"],
        "avisos": resultado["avisos"],
        "hallazgos": resultado["hallazgos"],
        "senales": resultado["senales"],
        "score_declarado": resultado["score_declarado"],
        "score_recalculado": resultado["score_recalculado"],
        "deltas_convergencia": resultado["deltas_convergencia"],
    }
    with open(destino, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(linea, ensure_ascii=False, sort_keys=True) + "\n")


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Decide corte del Protocolo 95 desde el JSON del auditor."
    )
    parser.add_argument("--audit", help="Ruta al audit del auditor, o - para stdin")
    parser.add_argument("--run", help="Slug del RUN")
    parser.add_argument("--umbral", type=int, help="Umbral de cierre, default operativo 95")
    parser.add_argument("--ciclo", type=int, help="Numero de ciclo actual")
    parser.add_argument("--prev-score", help="Score anterior o - si no existe")
    parser.add_argument("--tope", type=int, help="Tope de ciclos declarado")
    parser.add_argument("--barrido-ok", type=int, choices=(0, 1), help="1 si barrido_refutados.py salio 0")
    parser.add_argument("--log", default=DEFAULT_LOG, help="Ruta JSONL de log; para pruebas manuales usa --log a un archivo aparte")
    parser.add_argument("--strict", action="store_true", help="Exit 2 si la accion no es CERRAR")
    parser.add_argument("--selftest", action="store_true", help="Ejecuta casos de prueba internos")
    return parser


def validar_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    requeridos = ["audit", "run", "umbral", "ciclo", "prev_score", "tope"]
    faltan = [nombre.replace("_", "-") for nombre in requeridos if getattr(args, nombre) is None]
    if faltan:
        parser.error("faltan argumentos requeridos: " + ", ".join("--" + item for item in faltan))


def caso_selftest(
    nombre: str,
    audit: Dict[str, Any],
    esperado: Dict[str, Any],
    umbral: int = 95,
    ciclo: int = 1,
    prev_score: Optional[int] = None,
    tope: int = 3,
    historial_scores: Optional[list[int]] = None,
    barrido_ok: Optional[int] = None,
) -> bool:
    if "_veredicto_linea" not in audit:
        audit = dict(audit)
        audit["_veredicto_linea"] = leer_veredicto(audit.get("veredicto"))
    resultado = evaluar(audit, umbral, ciclo, prev_score, tope, historial_scores, barrido_ok)
    ok = all(resultado.get(k) == v for k, v in esperado.items())
    estado = "OK" if ok else "FAIL"
    print(f"{estado} {nombre}")
    if not ok:
        print(json.dumps({"esperado": esperado, "resultado": resultado}, ensure_ascii=False))
    return ok


def selftest() -> int:
    estado_log_default = estado_archivo(DEFAULT_LOG)
    gate_ok = {clave: True for clave in GATE_KEYS}
    gate_fail = {clave: False for clave in GATE_KEYS}
    dims_80 = {clave: 8 for clave in PESOS}
    dims_96 = {clave: 9.6 for clave in PESOS}
    casos = [
        caso_selftest(
            "FALLA por grave",
            {"veredicto": "FALLA", "gate": gate_fail, "score": 99, "dimensiones": dims_96, "hallazgos": [{"sev": "GRAVE"}]},
            {"accion": "SIGUE", "score": 94, "gate_pass": False, "veredicto": "FALLA"},
        ),
        caso_selftest(
            "PASA>=95 sin barrido-ok no cierra",
            {"veredicto": "PASA", "gate": gate_ok, "score": 96, "dimensiones": dims_96, "hallazgos": []},
            {"accion": "SIGUE", "score": 96, "gate_pass": True, "veredicto": "PASA", "motivo": "barrido_no_verificado"},
        ),
        caso_selftest(
            "PASA>=95 con barrido-ok=0 no cierra",
            {"veredicto": "PASA", "gate": gate_ok, "score": 96, "dimensiones": dims_96, "hallazgos": []},
            {"accion": "SIGUE", "score": 96, "gate_pass": True, "veredicto": "PASA", "motivo": "barrido_refutados_no_cero"},
            barrido_ok=0,
        ),
        caso_selftest(
            "tope domina barrido no cero",
            {"veredicto": "PASA", "gate": gate_ok, "score": 96, "dimensiones": dims_96, "hallazgos": []},
            {"accion": "PARA_TOPE", "score": 96, "gate_pass": True, "veredicto": "PASA", "motivo": "el ciclo alcanzo el tope declarado"},
            ciclo=5, tope=5, barrido_ok=0,
        ),
        caso_selftest(
            "PASA>=95 con barrido-ok=1 cierra",
            {"veredicto": "PASA", "gate": gate_ok, "score": 96, "dimensiones": dims_96, "hallazgos": []},
            {"accion": "CERRAR", "score": 96, "gate_pass": True, "veredicto": "PASA"},
            barrido_ok=1,
        ),
        caso_selftest(
            "correccion ABIERTA no cierra",
            {"veredicto": "PASA", "gate": gate_ok, "score": 96, "dimensiones": dims_96, "hallazgos": [], "correcciones": [{"hallazgo": "G1", "estado": "abierto", "evidencia": "pendiente"}]},
            {"accion": "SIGUE", "score": 94, "gate_pass": False, "veredicto": "FALLA", "motivo": "correccion_abierta"},
            barrido_ok=1,
        ),
        caso_selftest(
            "correccion ABIERTA no simula score bajo",
            {"veredicto": "PASA", "gate": gate_ok, "score": 96, "dimensiones": dims_96, "hallazgos": [], "correcciones": [{"hallazgo": "G1", "estado": "ABIERTO", "evidencia": "pendiente"}]},
            {"accion": "SIGUE", "score": 94, "gate_pass": False, "veredicto": "FALLA", "motivo": "correccion_abierta"},
            prev_score=96, barrido_ok=1,
        ),
        caso_selftest(
            "inconsistencia_auditor no cierra",
            {"veredicto": "PASA", "gate": gate_ok, "score": 96, "dimensiones": dims_96, "hallazgos": [{"sev": "GRAVE"}]},
            {
                "accion": "SIGUE",
                "score": 94,
                "gate_pass": False,
                "veredicto": "FALLA",
                "motivo": "inconsistencia_auditor",
                "avisos": ["inconsistencia_auditor"],
            },
        ),
        caso_selftest(
            "score_discrepancia usa dimensiones",
            {"veredicto": "PASA", "gate": gate_ok, "score": 99, "dimensiones": dims_80, "hallazgos": []},
            {"accion": "SIGUE", "score": 80, "gate_pass": True, "avisos": ["score_discrepancia"]},
        ),
        caso_selftest(
            "score_sin_dimensiones usa recalculado",
            {"veredicto": "PASA", "gate": gate_ok, "score": 99, "hallazgos": []},
            {"accion": "SIGUE", "score": 0, "gate_pass": True, "avisos": ["score_discrepancia"]},
        ),
        caso_selftest(
            "veredicto linea vs JSON no cierra",
            parsear_audit('VEREDICTO: FALLA\n{"veredicto":"PASA","gate":%s,"score":99,"dimensiones":%s,"hallazgos":[]}' % (json.dumps(gate_ok), json.dumps(dims_96))),
            {"accion": "SIGUE", "score": 94, "gate_pass": False, "veredicto": "FALLA", "motivo": "veredicto_linea_vs_json_mismatch"},
        ),
        caso_selftest(
            "un delta no converge",
            {"veredicto": "PASA", "gate": gate_ok, "score": 80, "dimensiones": dims_80, "hallazgos": []},
            {"accion": "SIGUE", "score": 80, "gate_pass": True, "veredicto": "PASA"},
            ciclo=2, prev_score=78, tope=5, historial_scores=[78],
        ),
        caso_selftest(
            "dos deltas converge",
            {"veredicto": "PASA", "gate": gate_ok, "score": 80, "dimensiones": dims_80, "hallazgos": []},
            {"accion": "PARA_CONVERGENCIA", "score": 80, "gate_pass": True, "veredicto": "PASA"},
            ciclo=2, prev_score=78, tope=5, historial_scores=[76, 78],
        ),
    ]
    log_ok = estado_archivo(DEFAULT_LOG) == estado_log_default
    print(f"{'OK' if log_ok else 'FAIL'} selftest no toca log default")
    return 0 if all(casos) and log_ok else 1


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)

    if args.selftest:
        args.log = os.devnull
        return selftest()

    validar_args(args, parser)
    prev_score = parse_prev_score(args.prev_score)
    audit = leer_audit(args.audit)
    historial_scores = leer_historial_scores(args.log, args.run, args.ciclo)
    resultado = evaluar(audit, args.umbral, args.ciclo, prev_score, args.tope, historial_scores, args.barrido_ok)
    escribir_log(args.log, args.run, args.ciclo, args.umbral, prev_score, resultado)

    salida = {
        "accion": resultado["accion"],
        "score": resultado["score"],
        "gate_pass": resultado["gate_pass"],
        "veredicto": resultado["veredicto"],
        "motivo": resultado["motivo"],
        "motivos": resultado["motivos"],
        "avisos": resultado["avisos"],
    }
    if resultado["score_declarado"] is not None:
        salida["score_declarado"] = resultado["score_declarado"]
    if resultado["score_recalculado"] is not None:
        salida["score_recalculado"] = resultado["score_recalculado"]
    print(json.dumps(salida, ensure_ascii=False, sort_keys=True))

    if args.strict and resultado["accion"] != "CERRAR":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
