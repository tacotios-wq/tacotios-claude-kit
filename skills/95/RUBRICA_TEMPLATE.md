# RUBRICA — Protocolo 95

Usar esta plantilla para crear `RUBRICA.md` dentro de cada RUN. La rubrica se pre-registra antes del ciclo 1 y queda INMUTABLE tras ese ciclo. Si la tarea cambia de verdad, escribir un `BRIEF_v2.md` fechado y una rubrica v2 declarando el pivote.

## Como rellenarla

- Convertir la tarea en checks observables sobre archivos, rutas, comandos o resultados.
- Hacer que cada check sea verificable leyendo el entregable completo, no por keywords sueltas.
- Marcar como GRAVE cualquier incumplimiento que rompa el uso prometido o impida auditar.
- Marcar como MEDIO lo que degrada la calidad pero mantiene el uso viable.
- Marcar como LEVE lo que conviene mejorar sin bloquear el cierre.
- Mantener dimensiones D1..D6 con pesos fijos salvo que el usuario pida otra matriz antes de arrancar.

## PARTE A — GATE BINARIO DE COMPLETITUD

El veredicto es FALLA si hay al menos 1 hallazgo GRAVE o al menos 3 hallazgos MEDIO. Todos los checks deben poder verificarse contra disco.

C1. Existe el entregable principal en la ruta absoluta declarada en BRIEF y abre sin error.
C2. El entregable implementa el objetivo central descrito en TAREA y USO.
C3. Cada criterio de exito verificable del BRIEF tiene evidencia real en el entregable.
C4. No hay pseudocodigo, texto de relleno ni instrucciones imposibles en partes ejecutables.
C5. Los comandos o scripts declarados corren en local o reportan una limitacion real.
C6. Las restricciones de ruta, seguridad y alcance del BRIEF se cumplen.
C7. Los supuestos riesgosos se reducen, se validan o quedan reportados con precision.
C8. Los hallazgos previos del ciclo anterior se verifican uno a uno como CERRADO o ABIERTO.
C9. No se introducen cambios fuera de los entregables autorizados.
C10. El resultado final es reanudable: run, logs, prompts y auditorias quedan en disco.

## PARTE B — SCORE DE CALIDAD

Calcular `score = round(100 * sum(peso * nota) / sum(peso * 10))`. Si el gate binario FALLA, reportar score pero considerar capado a 94 por `gate_95.py`.

D1 peso 3 — Fidelidad al objetivo: la solucion cubre lo pedido sin desplazar la tarea.
D2 peso 3 — Ejecutabilidad real: los archivos existen, se ejecutan y no dependen de pasos ocultos.
D3 peso 3 — Robustez ante fallos conocidos: maneja errores, edge cases y riesgos del BRIEF.
D4 peso 2 — Claridad operativa: otro modelo puede continuar el trabajo desde los artefactos.
D5 peso 2 — Minimalismo util: no infla alcance, texto ni arquitectura sin aumentar score.
D6 peso 2 — Encaje del ecosistema: respeta convenciones, rutas, nombres y herramientas existentes.

## ESQUEMA JSON DEL AUDITOR

Primera linea exacta:

```text
VEREDICTO: PASA
```

o:

```text
VEREDICTO: FALLA
```

Luego devolver un unico objeto JSON valido:

```json
{
  "veredicto": "PASA",
  "score": 95,
  "gate": {
    "C1": true,
    "C2": true,
    "C3": true,
    "C4": true,
    "C5": true,
    "C6": true,
    "C7": true,
    "C8": true,
    "C9": true,
    "C10": true
  },
  "dimensiones": {
    "D1": 10,
    "D2": 10,
    "D3": 9,
    "D4": 9,
    "D5": 9,
    "D6": 10
  },
  "hallazgos": [
    {
      "sev": "LEVE",
      "archivo": "~/.claude/skills/95/SKILL.md",
      "linea": 1,
      "que": "Descripcion verificable del problema encontrado",
      "accion": "Cambio concreto necesario para cerrarlo"
    }
  ],
  "correcciones": [
    {
      "hallazgo": "Identificador o descripcion del hallazgo previo",
      "estado": "CERRADO|ABIERTO",
      "evidencia": "archivo:linea"
    }
  ],
  "no_verificado": [
    "Aspecto que el auditor no pudo comprobar con los archivos disponibles"
  ]
}
```

Usar `veredicto` FALLA si hay al menos 1 GRAVE o al menos 3 MEDIO. En ciclos 2+, verificar hallazgos previos antes de buscar nuevos y registrarlos en `correcciones`; si no hay previos, usar `[]`.
