---
name: 95
description: |
  Protocolo 95% — loop autonomo CONSTRUCCION -> AUDITORIA -> AUTOPROMPTEO con Codex
  CLI (codex exec) como constructor y juez externo. Cada ciclo: autodiagnostico ->
  jerarquiza fallas por impacto/esfuerzo -> disena el prompt -> codex exec construye ->
  council ligero de contrapuntos -> codex exec audita a ciegas y cualifica el % (gate
  binario de completitud + score vs rubrica pre-registrada) -> si <95 el sistema se
  autopromptea el siguiente ciclo con los errores como input. Corre hasta >=95 O
  convergencia (2 ciclos sin mejora >=5 puntos) O tope de ciclos/presupuesto. Frenos:
  se detiene si el score baja, si se estanca, o si va a superar el presupuesto declarado.
  Usar con: /95 [tarea], "protocolo 95", "llevalo al 95%", "loop hasta 95",
  "construyelo y auditalo hasta que pase".
  NO usar dentro de otra skill que ya traiga sus propios ciclos y gates.
  NO para tareas mecanicas scriptables (agente barato) ni decisiones irreversibles
  >$500 (ahi conviene analisis profundo con revision humana). Diferencia con /exponencial: aquel corre 3 ciclos hasta
  PASA/FALLA; /95 es loop autopromptado hasta cruzar un umbral de score medido o converger.
  No se auto-dispara: lo invoca el usuario.
  MODOS:
    /95 [tarea]               -> default, umbral 95, tope de ciclos y presupuesto por defecto
    /95 [tarea] --umbral N    -> cambia el umbral de corte
    /95 [tarea] --presupuesto -> declara tope de tokens/ciclos antes de arrancar
---

# Protocolo 95

## 1. LEY MADRE

El auditor NUNCA es la cabeza que construyo. El gate lo cierra `codex exec` de verdad, o no se cierra.

Reparto obligatorio:

- Una cabeza, el modelo activo, disena la spec y la rubrica.
- Codex CONSTRUYE con `codex exec -s workspace-write`.
- Codex AUDITA en llamada SEPARADA con `codex exec -s read-only`, contra la rubrica escrita, leyendo los archivos completos y sin muestrear.
- Prohibido sustituir el auditor por autocritica, por un subagente o por una revision del mismo constructor.

## 2. PASO 0 · PREVUELO Y ENCUADRE

Ejecutar una sola vez antes del ciclo 1:

1. Verificar Codex vivo con un smoke test real. `command -v codex` no basta: lanzar un `codex exec` minimo y guardar log.
2. Crear un RUN en `<cwd>/_95/AAAAMMDD-<slug>/`.
3. Escribir `<RUN>/BRIEF.md` con contrato de 20 lineas o menos:
   - TAREA.
   - USO.
   - CRITERIOS DE EXITO verificables.
   - ENTREGABLES con rutas absolutas.
   - SUPUESTO RIESGOSO.
4. Escribir `<RUN>/RUBRICA.md` PARTIENDO SIEMPRE de `RUBRICA_TEMPLATE.md` de esta
   skill. Se copia y se adaptan los TEXTOS de cada check y dimension; nunca las
   claves. El contrato es fijo y no se inventa:
   - Gate binario: exactamente `C1` a `C10`. `gate_95.py` exige que las diez
     existan y sean `true`; con A1-A9 o cualquier otro nombre, `gate_todo_true()`
     devuelve False siempre y el gate es imposible de pasar.
   - Calidad: clave `dimensiones` con `D1` a `D6`, pesos 3/3/3/2/2/2. Con `B1-B5`
     u otro nombre, `score_recalculado` sale 0 y dispara un `PARA_SCORE_BAJA` falso.
   - El JSON lleva ademas `veredicto` con valor PASA o FALLA, que debe coincidir
     con la primera linea del auditor, mas `hallazgos` y `no_verificado`.
   Escribir una rubrica desde cero sin abrir la plantilla es el fallo mas caro y
   mas repetido del protocolo: el 2026-08-24 quemo dos ciclos completos, y en el
   log historico hay 42 `PARA_SCORE_BAJA` sobre 176 entradas.
5. Congelar BRIEF y RUBRICA tras el ciclo 1. No editarlos; un pivote se escribe como `BRIEF_v2.md` fechado y se declara en el CONTEXT.
6. Autodetectar profundidad con 5 senales: irreversibilidad, multidimensionalidad, alto impacto, incertidumbre, multi-stakeholder. Mas senales implican mas ciclos, mas presupuesto y auditoria mas estricta.
7. Declarar presupuesto antes de arrancar: umbral, tope de ciclos, tope de tokens o tiempo, y condicion de parada por presupuesto.
8. Leer antes de arrancar `LIMITES_CONOCIDOS.md` de esta skill y la ficha de
   memoria `project_protocolo_95.md`. Ambas acumulan los fallos ya pagados. No
   sustituye recordarlos: se abren.
9. Escribir `<RUN>/CHECKS.json` y dejar que el gate binario lo calcule
   `check_mecanico.py` (ver seccion 3-bis). Un check que el auditor no pueda
   probar leyendo archivos no va en la rubrica: va en el verificador o no va.
10. Declarar el umbral segun la naturaleza del entregable. Sobre CODIGO, 95 es
   alcanzable porque un test verde es verde. Sobre PROSA el juez tiene varianza
   alta: medido el 2026-08-24, con el gate mecanico en verde y sin cambios
   estructurales, el mismo trabajo puntuo 85, 79 y 82 en ciclos consecutivos.
   Para prosa, o se declara un umbral menor, o se aceptan mas checks mecanicos,
   o se asume que cerrar en PARA_TOPE con gate verde es un resultado legitimo.

## 3. EL BLOQUE DEL GATE CODEX

Copiar este bloque exactamente. El auditor y el constructor comparten este patron cambiando el sandbox.

```bash
# variables del ciclo
: "${RUN:?define RUN}"; : "${N:?define N (numero de ciclo)}"; : "${TARGET:?define TARGET}"
: "${CWD_LIMPIO:?define CWD_LIMPIO fuera de ~/.claude}"; : "${UMBRAL:?define UMBRAL}"; : "${TOPE:?define TOPE}"
: "${PREV_SCORE:=-}"
AUDIT_TMP="$CWD_LIMPIO/C${N}_AUDIT.md"
AUDIT_RETRY="$CWD_LIMPIO/C${N}_AUDITPROMPT_RETRY.md"

# el bloque corre en bash o zsh sin variables que dependan de word-splitting

# CONSTRUCTOR (escribe archivos)
codex exec --ignore-user-config -m gpt-5.6-sol -c mcp_servers='{}' -c model_reasoning_effort=xhigh --skip-git-repo-check -s workspace-write -C "$CWD_LIMPIO" --add-dir "$TARGET" -o "$RUN/C${N}_BUILD.md" - < "$RUN/C${N}_BUILDPROMPT.md" > "$RUN/C${N}_BUILDLOG.txt" 2>&1 || echo "BUILD exit!=0, ver C${N}_BUILDLOG.txt"

# AUDITOR (read-only, juez externo) — anti-stale primero
rm -f "$RUN/C${N}_AUDIT.md" "$RUN/C${N}_NOAUDIT" "$AUDIT_TMP" "$AUDIT_RETRY"
AUDIT_STATUS=0
codex exec --ignore-user-config -m gpt-5.6-sol -c mcp_servers='{}' -c model_reasoning_effort=xhigh --skip-git-repo-check -s read-only -C "$CWD_LIMPIO" -o "$AUDIT_TMP" - < "$RUN/C${N}_AUDITPROMPT.md" > "$RUN/C${N}_AUDITLOG.txt" 2>&1 || AUDIT_STATUS=$?
if [ "$AUDIT_STATUS" -ne 0 ]; then
  echo "NO-AUDITADO $(date '+%F %T'): codex exec exit!=0, ver C${N}_AUDITLOG.txt" | tee "$RUN/C${N}_NOAUDIT"
else
  # parseo estricto del veredicto (primera linea) con un reintento real
  if ! head -1 "$AUDIT_TMP" | grep -Eq '^VEREDICTO: (PASA|FALLA)$'; then
    { echo "Tu primer renglon DEBE ser exactamente VEREDICTO: PASA o VEREDICTO: FALLA"; echo; cat "$RUN/C${N}_AUDITPROMPT.md"; } > "$AUDIT_RETRY"
    rm -f "$AUDIT_TMP"
    codex exec --ignore-user-config -m gpt-5.6-sol -c mcp_servers='{}' -c model_reasoning_effort=xhigh --skip-git-repo-check -s read-only -C "$CWD_LIMPIO" -o "$AUDIT_TMP" - < "$AUDIT_RETRY" > "$RUN/C${N}_AUDITLOG_RETRY.txt" 2>&1 || AUDIT_STATUS=$?
    if [ "$AUDIT_STATUS" -ne 0 ]; then
      echo "NO-AUDITADO $(date '+%F %T'): retry auditor exit!=0, ver C${N}_AUDITLOG_RETRY.txt" | tee "$RUN/C${N}_NOAUDIT"
    fi
  fi

  if [ "$AUDIT_STATUS" -eq 0 ]; then
    if head -1 "$AUDIT_TMP" | grep -Eq '^VEREDICTO: (PASA|FALLA)$'; then
      rm -f "$RUN/C${N}_NOAUDIT"
      cp "$AUDIT_TMP" "$RUN/C${N}_AUDIT.md"
      BARRIDO_OK=0
      if python3 ~/.claude/bin/barrido_refutados.py "$TARGET"; then
        BARRIDO_OK=1
      fi
      python3 ~/.claude/skills/95/gate_95.py --audit "$RUN/C${N}_AUDIT.md" --run "$(basename "$RUN")" --umbral "$UMBRAL" --ciclo "$N" --prev-score "$PREV_SCORE" --tope "$TOPE" --barrido-ok "$BARRIDO_OK"
    else
      echo "NO-AUDITADO $(date '+%F %T'): veredicto invalido tras 1 reintento" | tee "$RUN/C${N}_NOAUDIT"
    fi
  fi
fi
```

Codex lee `~/.claude` aunque el cwd este fuera: `CWD_LIMPIO` debe ser temporal, fuera de `~/.claude` y sin `.codex/` en su arbol; `TARGET` es el arbol del entregable que puede escribir el constructor. Si el `grep` no matchea tras el reintento, el ciclo queda NO-AUDITADO y el bloque no llama al gate.

Nota critica: `--ignore-user-config`, `-C "$CWD_LIMPIO"` fuera de `~/.claude`, `--add-dir "$TARGET"` en constructor y `-c mcp_servers='{}'` aislan MCP; no quitar ninguno.

## 3-bis. GATE MECANICO

Los checks `C1` a `C10` los calcula un script, no el juez:

```bash
touch "$RUN/.ciclo_start"                      # al inicio de CADA ciclo
python3 ~/.claude/skills/95/check_mecanico.py "$RUN" > "$RUN/C${N}_MEC.json"
```

Su salida se pega dentro del auditprompt bajo un titulo VERIFICADOR MECANICO,
con la instruccion de que el auditor la COPIE tal cual en su JSON y no la
re-juzgue. El juez puntua `D1` a `D6` y escribe hallazgos; el gate binario deja
de depender de su criterio.

Motivo: los checks de tipo "no escribio fuera del directorio" o "cero datos
inventados" son inverificables leyendo, y el auditor los marcaba en rojo por
archivos que habia tocado otra sesion. Un gate con checks inverificables no pasa
nunca. Los tipos declarativos disponibles y el formato de `CHECKS.json` estan
documentados en la cabecera de `check_mecanico.py`.

## 4. EL CICLO

Repetir las fases por vuelta `N`.

### FASE 1 AUTODIAGNOSTICO

Leer estado SOLO de disco: `BRIEF.md`, `RUBRICA.md`, `MEMORIA.md` si existe y el ultimo `C*_AUDIT.md`. Jerarquizar las fallas pendientes por impacto y esfuerzo, cada uno 1-10, con `ratio = impacto / esfuerzo`. Elegir UN solo Punto 0 por ciclo: el hallazgo GRAVE de mayor ratio. No arreglar varias cosas a la vez si compiten por atencion.

### FASE 2 PLAN + PROMPT

Mapear que piezas aplican y redactar `<RUN>/C${N}_BUILDPROMPT.md`. Usar spec reasoning-native: instrucciones positivas, criterios de aceptacion, rutas absolutas, sin pedir cadena de pensamiento y sin XML. En ciclos 2+ el prompt lleva los hallazgos del audit anterior como audit diferencial.

### FASE 3 EJECUTAR

Codex-constructor escribe archivos con `workspace-write`. Luego ejecutar PRE-GATE BARATO local antes de gastar auditor: correr el codigo, abrir rutas, contar lineas, releer contra BRIEF y revisar que no se haya escrito fuera de las rutas permitidas.

### FASE 4 COUNCIL LIGERO

Usar tres lentes que alimentan contrapuntos, no sentencian:

- HUECOS: que exige la tarea y no esta.
- CONTRADICCIONES: claims vs BRIEF, rubrica o datos.
- EXCESO/PODA: alcance no pedido, relleno y crecimiento inutil; esta lente RECORTA.

Agregar PULSO CHECK: preguntar si el ciclo anterior tenia algo crudo y valioso que este perdio. Por defecto, integrar las tres lentes en el prompt del auditor Codex para mantener coste bajo. Usar una lente-alma extra en Claude solo si la tarea es de voz o contenido.

### FASE 5 GATE + SCORE

Codex-auditor audita a ciegas contra `RUBRICA.md`. Solo ve `BRIEF.md`, `RUBRICA.md` y un CONTEXT factual de 4 bloques: QUE SE ELIGIO, SUPUESTOS, PENDIENTES, RECHAZOS A RE-JUZGAR. Nunca ve tu razonamiento ni la MEMORIA interna. Devuelve `VEREDICTO: PASA|FALLA` y JSON de score. El bloque del gate llama a `gate_95.py` solo si la primera linea es valida.

Metrica hibrida: primero gate binario de completitud; despues score de calidad por rubrica. Si el gate FALLA, `gate_95.py` capa el score a 94 aunque el auditor haya inflado la nota.

### FASE 6 CORTE O AUTOPROMPTEO

`gate_95.py` decide:

- CERRAR si `score >= umbral`, gate PASA y el barrido de refutados da cero.
- PARA_CONVERGENCIA si hay 2 ciclos sin mejora de 5 puntos o mas.
- PARA_TOPE si se agoto el tope de ciclos o presupuesto.
- PARA_SCORE_BAJA si el score bajo; detener y consultar al usuario.
- SIGUE si nada corta.

Si SIGUE, comprimir `MEMORIA.md` a 40 lineas o menos, sobrescribiendo con secciones HECHOS, DECISIONES, SUPUESTOS, RIESGOS y PENDIENTES. Generar el autoprompt del siguiente ciclo con los hallazgos como input y volver a FASE 1.

## 5. PROPAGACION DE REFUTACIONES

Cada hallazgo confirmado entra a un ledger de refutaciones en el RUN. El ciclo no cierra hasta que:

```bash
python3 ~/.claude/bin/barrido_refutados.py "$TARGET"
```

devuelve cero. Antes de aceptar CERRAR, pasar ese exit code como `--barrido-ok`: `1` si fue 0, `0` si no. Sin `--barrido-ok 1`, `gate_95.py` falla cerrado y devuelve SIGUE. Un hallazgo esta cerrado cuando el auditor lo verifica leyendo el archivo completo, no cuando el constructor dice que lo corrigio. En ciclos 2+, el auditor verifica los hallazgos previos uno a uno como CERRADO o ABIERTO antes de buscar nuevos.

## 6. ANTI-INFLADO

La lente de PODA es obligatoria. Reportar el porcentaje de crecimiento del entregable por ciclo:

```text
crecimiento_pct = round(100 * (tamano_actual - tamano_previo) / max(tamano_previo, 1))
```

Un ciclo que solo reescribe, expande o maquilla sin subir el score no cuenta como avance y cuenta para la convergencia. Recortar alcance no pedido es una mejora valida.

## 7. FRENOS

- Score baja: detener y consultar al usuario.
- Techo real, como asset, decision, credencial o dato que solo el usuario desbloquea: parar y reportar sin suavizar.
- Auto-modificacion de los propios ficheros de `/95`: pedir OK explicito por archivo antes de aplicar.
- Presupuesto a punto de superarse: no lanzar el siguiente `codex exec`; reportar el estado y pedir decision.
- La cabeza NO edita el entregable entre ciclos. Todo cambio lo hace el
  constructor dentro de un ciclo; si la cabeza corrige a mano, el auditor audita
  algo que nadie construyo y el diferencial deja de ser trazable.
- El CONTEXT del auditor declara TODAS las fuentes de datos con su n, no solo la
  principal. Si el juez cree que hay una sola fuente, marca como contradiccion
  cualquier cifra con otro n y fabrica hallazgos GRAVE falsos.
- El loop corre en background con `nohup`, desacoplado de la sesion. De 59 runs
  historicos, 23 murieron sin una sola auditoria porque la sesion se desvio antes
  de lanzar el primer ciclo.

## 8. REPORTE FINAL

Usar formato fijo:

```text
RESULTADO: existe en <ruta_absoluta> y estado <cerrado|parcial|no-auditado>
CICLOS: C1 VEREDICTO score; C2 VEREDICTO score
ABIERTO: lista concreta o "nada"
LIMITES DEL PASA: no_verificado textual del auditor
SUPUESTOS VIVOS: lista concreta o "nada"
RUN reanudable: <ruta_absoluta_del_RUN>
```

Reportar sin suavizar. Un exito parcial se reporta como parcial.

## 9. DIFERENCIA CON /exponencial

`/exponencial` corre 3 ciclos hasta PASA/FALLA; `/95` corre un loop autopromptado hasta cruzar un umbral de score medido o converger. Reglas duras: usar rutas absolutas.
