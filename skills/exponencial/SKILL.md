---
name: exponencial
description: >-
  Protocolo de máximo nivel por ciclos con auditor externo REAL (Codex CLI) como gate
  de cierre. Hasta 3 ciclos: ABRIR (divergir) → DECIDIR (filtrar) → EJECUTAR (aterrizar)
  → AUDITAR (codex exec, VEREDICTO PASA/FALLA) → COMPRIMIR (memoria operativa).
  Usar con: /exponencial [tarea], "modo exponencial", "trabaja esto por ciclos",
  "máximo nivel con auditoría", "que lo audite Codex" — en construcción, documentos,
  análisis o sistemas donde equivocarse cuesta y NO exista skill dedicada.
  NO usar dentro de /95 ni de otra skill que ya traiga sus propios ciclos y gates;
  NO para tareas mecánicas scriptables (agente barato) ni decisiones irreversibles
  >$500 (ahí conviene análisis profundo con revisión humana). No se auto-sugiere: la invoca el usuario.
---

# /exponencial — ciclos con auditor externo real

## Ley madre

El auditor NUNCA es la cabeza que decidió. Lección probada 2026-07-09: Fable verificó
su propio backup por muestreo y dijo OK; Codex, leyendo el árbol completo, encontró
3 huecos reales. El gate lo cierra `codex exec` de verdad, o no se cierra.

## Paso 0 — Gate de entrada y pre-vuelo (~1 min, sin ceremonia)

1. **Routing del ecosistema**: si la tarea cae en una skill con ciclos propios
   (por ejemplo /95 o cualquier skill de ciclos con auditor propio)
   → decir cuál y enrutar (en duda: preguntar al usuario). Decisión irreversible >$500
   → análisis profundo con revisión humana. Mecánico scriptable → agente barato / python. FIN en los tres casos.
2. **Codex vivo**: `command -v codex` por Bash. Si no está → avisar y NO arrancar.
   OJO: eso solo prueba el binario, no la red/auth; el fail-closed real es operativo:
   si el PRIMER `codex exec` del run sale con exit≠0, el run queda NO-AUDITADO y no
   se abre ciclo útil. Prohibido sustituir el auditor por subagente Claude o autocrítica.
3. **Reformular** (Fable R1): qué pide el usuario, qué hará con el resultado, el supuesto
   riesgoso, y criterios de éxito VERIFICABLES. Va al BRIEF, no a la conversación.
4. **Crear el run** (rutas SIEMPRE absolutas; jamás dentro de OPENCLOW PROJECTS/, Mare/
   ni 05_ADMINISTRATIVO_LEGAL/):

   ```bash
   RUN="$PWD/_expo/$(date +%Y%m%d)-<slug>"
   mkdir -p "$RUN"
   ```

   Archivos del run: `BRIEF.md`, `MEMORIA.md` (interno, NO viaja al auditor),
   `C{n}_CONTEXT.md` (lo único del decisor que Codex ve), `C{n}_PROMPT.md`,
   `C{n}_AUDIT.md`, `C{n}_LOG.txt`. El ENTREGABLE real vive donde deba vivir en el
   proyecto; BRIEF.md lista sus rutas absolutas.

### BRIEF.md (máx 20 líneas — es el contrato)

```
TAREA: [reformulación en 2 líneas]
USO: [qué hará el usuario con esto]
CRITERIOS DE ÉXITO (verificables): [3-6, medibles]
ENTREGABLES (rutas absolutas): [lista]
SUPUESTO RIESGOSO DECLARADO: [1 línea]
```

**BRIEF inmutable tras el ciclo 1.** Si el usuario pivota, se escribe `BRIEF_v2.md` fechado:
el examen no se reescribe en silencio para encajar con lo ya hecho.

## Mecánica honesta de modelos

En una sesión de Claude Code NO hay salto automático de modelo; el activo lo fija el usuario
con /model. Los roles se implementan así:

- **ABRIR / DECIDIR / EJECUTAR**: el modelo activo. Si la tarea merece /exponencial,
  merece Fable 5 — sugerirlo UNA vez si la sesión corre en otro modelo, sin insistir.
- **Producción mecánica larga** dentro de EJECUTAR (batch, scaffolding, formato):
  delegar a subagente Sonnet/Haiku o script python en una llamada. No quemar el hilo.
- **AUDITAR**: siempre `codex exec` por Bash. Externo real, nunca simulado. Codex
  factura contra su plan Plus: la auditoría cuesta ~0 tokens de la sesión Claude.
- **Código**: si Codex construyó algo en EJECUTAR (regla Codex-implementa), el
  Codex-auditor va en llamada SEPARADA y audita contra la spec escrita en DECIDIR,
  no contra lo que el constructor diga. Fable corre el código en el pre-gate.

## El ciclo (regla de información por fase)

**1. ABRIR** — explorando ⇒ profundo. Ciclo 1: 3 enfoques DISTINTOS de verdad + 1 línea
de trade-off cada uno (Fable R3). Ciclos 2-3: divergir SOLO sobre lo que el audit
anterior dejó abierto. No censurar ideas raras aquí.

**2. DECIDIR** — decidiendo ⇒ completo-limpio. Elegir UNA vía con argumentos; nunca
entregar el menú como respuesta. Registrar en MEMORIA.md: decisión + por qué + qué se
descartó. Si cambia el alcance → BRIEF_v2 explícito.

**3. EJECUTAR** — ejecutando ⇒ mínimo útil. Producir/modificar los archivos reales.
Pre-gate barato ANTES de gastar a Codex: correr el código, abrir las rutas, releer
contra BRIEF (Fable R5+R6). A entregables de texto, pase anti-relleno: recortar ~40%
sin perder ideas; si no se puede, había relleno estructural — rehacer la sección.

**4. AUDITAR** — gate externo (wiring abajo).

**5. CORREGIR + COMPRIMIR** — cierre del ciclo.
- Si FALLA: corregir cada GRAVE y MEDIO antes de abrir el siguiente ciclo. Rechazar un
  hallazgo solo con justificación escrita en MEMORIA.md (Codex la re-juzga en el
  siguiente audit). Los LEVE se corrigen si cuestan <2 min.
- COMPRIMIR siempre (pase o falle): reescribir MEMORIA.md COMPLETO (overwrite, no
  append). Extracción, no narrativa:

  ```
  ## HECHOS   ## DECISIONES   ## SUPUESTOS   ## RIESGOS   ## PENDIENTES
  (máx 40 líneas totales; cada línea sobrevive sola sin la conversación)
  ```

## AUDITAR — wiring exacto (verificado codex-cli 0.143.0, 2026-07-09)

Escribir `C{n}_PROMPT.md` (template abajo) y lanzar UNA llamada Bash
(timeout 600000 — Codex tarda 2-10 min):

```bash
# Ejecutable tal cual. RUN y N son EXPLÍCITOS (jamás default silencioso de ciclo):
: "${RUN:?RUN no inicializado — ejecuta el Paso 0 o --seguir RUTA_RUN}"
: "${N:?N no inicializado — declara el ciclo: 1, 2 o 3}"
[[ "$N" =~ ^[123]$ ]] || { echo "N=$N inválido (solo 1|2|3)"; exit 1; }
WORKDIR="${WORKDIR:-$PWD}"   # ancestro común de entregables y $RUN; el sandbox
rm -f "$RUN/C${N}_AUDIT.md" "$RUN/C${N}_NOAUDIT"   # anti-stale: nunca parsear viejo
if ! codex exec --skip-git-repo-check -s read-only -C "$WORKDIR" \
  -o "$RUN/C${N}_AUDIT.md" - < "$RUN/C${N}_PROMPT.md" > "$RUN/C${N}_LOG.txt" 2>&1; then
  echo "NO-AUDITADO $(date '+%F %T'): codex exec exit≠0, ver C${N}_LOG.txt" \
    | tee "$RUN/C${N}_NOAUDIT"   # el estado persiste EN DISCO, no solo en terminal
else
  # -o escribe SOLO el último mensaje → la 1ª línea DEBE ser el veredicto exacto:
  head -1 "$RUN/C${N}_AUDIT.md" | grep -E '^VEREDICTO: (PASA|FALLA)$' \
    || echo "sin veredicto parseable en línea 1 → reintento único o NO-AUDITADO"
fi
```

- `-` lee el prompt por stdin (cero quoting hell); `-o` escribe SOLO el mensaje final
  → veredicto limpio parseable. (Hardening futuro: `--output-schema`, una línea, no más.)
- El grep exige PASA o FALLA exactos: un "VEREDICTO: PASA?" o "NO SÉ" NO cierra el
  gate. grep sin match → 1 reintento añadiendo al prompt: "Tu último mensaje DEBE
  empezar por la línea exacta 'VEREDICTO: PASA' o 'VEREDICTO: FALLA'". Si vuelve a
  fallar → el gate queda **NO-AUDITADO** y se reporta así, textual. Prohibido inventar
  el veredicto o degradarlo a autocrítica.

**Auditoría CIEGA (regla dura):** lo ÚNICO del decisor que viaja a Codex es
`C{n}_CONTEXT.md`, con exactamente 4 bloques: QUÉ SE ELIGIÓ (decisiones factuales,
sin porqués), SUPUESTOS, PENDIENTES DECLARADOS, y RECHAZOS A RE-JUZGAR (hallazgos
previos rechazados, cada uno con su justificación — viajan porque su re-juicio es la
función del auditor). NUNCA viajan: el razonamiento general, la auto-evaluación, ni
MEMORIA.md (archivo interno). Un auditor que lee tu justificación audita tu narrativa;
uno ciego audita tus archivos.

## Template del prompt de auditoría (C{n}_PROMPT.md)

```
Actúas como auditor externo. NO participaste en crear este trabajo. Tu trabajo es
encontrar lo que el autor no vio; validar sin buscar es fallar tu trabajo. Tampoco
inventes hallazgos para parecer duro: cada uno debe ser verificable en los archivos.

TAREA ORIGINAL (tu vara de auditoría):
[BRIEF.md íntegro]

CICLO [n] DE 3. CONTEXTO DEL DECISOR (C{n}_CONTEXT.md íntegro):
[QUÉ SE ELIGIÓ / SUPUESTOS / PENDIENTES DECLARADOS / RECHAZOS A RE-JUZGAR]

[solo ciclo 1] AUDITA PRIMERO EL EXAMEN: ¿los criterios del BRIEF son medibles?
¿Hay un criterio tan blando que se auto-aprueba? ¿Falta declarar un supuesto riesgoso?
Si el contrato está mal, dilo como hallazgo GRAVE antes de tocar el entregable.

[solo ciclos 2+] TUS HALLAZGOS ANTERIORES:
[hallazgos del audit previo]
Verifica UNO A UNO si están corregidos de verdad: lee el archivo, no confíes en la
nota de corrección.

ARCHIVOS A AUDITAR — léelos COMPLETOS, no muestrees:
- [ruta absoluta entregable 1..n]
(los supuestos y pendientes están arriba en el contexto; puedes retarlos)

BUSCA en este orden:
1. HUECOS: qué exige la tarea original y no está.
2. CONTRADICCIONES: internas, o contra BRIEF.md y el contexto del decisor de arriba.
3. EXCESO: relleno o alcance no pedido que debería cortarse.
4. RIESGOS: qué se rompe primero al usarse en el mundo real.

SALIDA OBLIGATORIA — tu ÚLTIMO mensaje, exactamente:
VEREDICTO: PASA | FALLA
(FALLA si hay ≥1 GRAVE o ≥3 MEDIO — el umbral es fijo, no a tu discreción)
[solo ciclos 2+] CORRECCIONES: [cada hallazgo previo: CERRADO/ABIERTO + evidencia leída]
HALLAZGOS: [severidad GRAVE/MEDIO/LEVE + archivo:línea + qué + ACCIÓN concreta]
VIAS DE ATAQUE INTENTADAS: [si PASA: qué intentaste romper y no rompió — sin cuota]
NO_VERIFICADO: [lo que tu sandbox read-only no pudo comprobar — obligatorio]
```

## Gate y convergencia

- **PASA** → early-exit inmediato: no se queman ciclos por ceremonia. Reporte final.
- **FALLA** → corregir → siguiente ciclo con audit diferencial (los hallazgos previos
  van en el prompt; Codex verifica correcciones primero, luego busca nuevos).
- **Tope duro: 3 ciclos / 3 audits.** Si el ciclo 3 FALLA: corregir lo corregible y
  REPORTAR lo abierto hallazgo por hallazgo, sin re-auditar y sin suavizar (Fable R7).
  Nunca declarar un PASA que Codex no dio.

## Niveles (la consulta rápida NO entra al protocolo)

| Nivel | Cuándo | Ciclos |
|---|---|---|
| 2 | doc corto / decisión mediana con criterios claros | 1 |
| 3 | entregable mediano (informe, spec, script) | 1-2 |
| 4 | **default**: entregable a terceros, análisis con números, construcción | hasta 3 |
| 5 | manual maestro / arquitectura / sistema — ABRIR con subagentes paralelos | hasta 3 |

Nivel 4-5 ocupa slot tier-S del día (máx 1-2 piezas caras; budget guard aplica al
número de runs, no a la profundidad de cada run).

## Reanudar un run (`/exponencial --seguir RUTA_RUN`) — fail-closed

El estado se reconstruye SOLO desde disco, nunca de memoria de conversación:
1. Leer `BRIEF.md` (o `BRIEF_v2.md` si existe, el más reciente), `MEMORIA.md` y el
   último `C{n}_AUDIT.md` del run.
2. Determinar el estado: último veredicto + hallazgos GRAVE/MEDIO sin corregir.
   Si existe `C{n}_NOAUDIT` (o un audit sin veredicto parseable), ese gate quedó
   NO-AUDITADO: se retoma re-lanzando ESE audit, nunca saltándolo (fail-closed).
3. Si hay GRAVE/MEDIO abiertos → se retoma en fase CORREGIR de ese ciclo; prohibido
   abrir ciclo nuevo con hallazgos abiertos. Si el último audit fue PASA → el run
   estaba cerrado; reabrir exige BRIEF_v2. Si no hay ningún audit → retomar en
   EJECUTAR del ciclo 1.
4. Si falta BRIEF.md o el run no existe → reportarlo y parar. No se improvisa contrato.

## Reporte final (formato fijo)

```
[1ª línea: el resultado — qué existe ahora y dónde]
CICLOS: [n] — veredictos: [C1 FALLA(2G,1M) → C2 PASA]
ABIERTO: [hallazgos no resueltos, uno por línea, o "nada"]
LÍMITES DEL PASA: [el NO_VERIFICADO de Codex, textual]
SUPUESTOS VIVOS: [los que siguen sin confirmar]
RUN: [ruta absoluta — reanudable con /exponencial --seguir RUTA]
```

## Reglas duras

1. Auditoría real o no es /exponencial: sin Codex vivo, no se arranca.
2. El autor nunca se auto-aprueba; el gate lo cierra la otra cabeza.
3. Todo estado importante vive EN DISCO (BRIEF, MEMORIA, audits) — lo que quede solo
   en la conversación se declara PENDIENTE o se vuelca antes de cerrar el ciclo.
4. MEMORIA.md ≤ 40 líneas, overwrite por ciclo; es extracción, no resumen narrativo.
5. Corrección de GRAVE/MEDIO antes que ciclo nuevo; rechazo solo por escrito.
6. $WORKDIR jamás en rutas intocables (OPENCLOW PROJECTS/, Mare/, 05_ADMINISTRATIVO_LEGAL/).
7. Anti-deriva: releer BRIEF.md al abrir cada ciclo (Fable R6).
8. Mecánico → barato: batch/formato a Sonnet/Haiku/python, nunca al hilo principal.
9. BRIEF inmutable post-ciclo-1; pivote = BRIEF_v2 fechado.
10. Al cerrar, log de 1 línea JSON a `~/.claude/memory/exponencial_log.jsonl`:
    `{ts, tarea, nivel, ciclos, veredicto_final, hallazgos: {grave, medio, leve}}`.
    Revisión MANUAL.
    Hallazgo repetido entre runs = defecto del método → parche a esta skill.
