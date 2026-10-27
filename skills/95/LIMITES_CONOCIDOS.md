# LIMITES CONOCIDOS — /95 v1.0 (CERRADA por gate, 2026-07-23)

Estado: el bootstrap cerro con `accion: CERRAR`, VEREDICTO PASA, score 97/100, gate binario 10/10, barrido de refutados en cero. NO quedan hallazgos abiertos.

## Limites que existieron y estan CERRADOS (trazabilidad)
- L1 (GRAVE) el tope no dominaba las ramas SIGUE -> CERRADO ciclo 6 (gate_95.py:244 orden de precedencia comentado; caso de selftest ciclo>=tope + barrido 0 => PARA_TOPE).
- L2 (MEDIO) el freno de score bajo se disparaba por el capado y mentia el motivo -> CERRADO ciclo 6 (compara score recalculado sin capar).
- L3 (GRAVE de higiene) el --selftest contaminaba el log de produccion -> CERRADO ciclo 6 (usa temporal; verificado: log 3024 -> 3024 bytes tras correr el selftest). El log historico se saneo: backup del contaminado en _95/20260722-bootstrap/95_log.jsonl.contaminado.bak.
- Historicos cerrados en ciclos 2-5: H1-H6, N1-N4, G1, G2 (15 hallazgos en total, cada uno verificado por el auditor leyendo el archivo).

## Limite estructural observado (no es un bug, es del metodo)
En un artefacto meta (una skill que se audita a si misma) el auditor adversarial sube el liston en cada ciclo. Durante los ciclos 3-5 el score se estanco en la meseta 83-86 y la parada util fue la CONVERGENCIA, no el umbral. Solo al atacar los defectos de precedencia e higiene (ciclo 6) el gate quedo 10/10 y el score salto a 97. Leccion: cuando el score se mesetea, revisar si los hallazgos restantes son de COHERENCIA INTERNA (precedencia, contratos declarados vs implementados); ahi suele estar el salto.

## Condiciones de operacion que NO son opcionales (verificadas en vivo)
1. Codex se invoca SIEMPRE aislado: `--ignore-user-config` + `-C` en un cwd FUERA de ~/.claude + `--add-dir <target>` + `-c mcp_servers='{}'`. Sin esto se cuelga por auth headless de los MCP del config (verificado dos veces, una en read-only y otra en workspace-write).
2. Modelo explicito `-m gpt-5.6-sol` (desde 15-oct-2026 la cuenta ChatGPT del usuario rechaza gpt-5.5 con error 400; gpt-5.6-sol es el default que acepta).
3. Nada de variables tipo `$CODEX` en los bloques: zsh no hace word-splitting y el comando falla con "command not found".
4. Para CERRAR hay que pasar `--barrido-ok 1` con el barrido en cero. El gate se niega a cerrar sin el (fail-closed, demostrado: se nego a cerrarse a si mismo hasta correr el barrido).
5. Cuidado con el instrumento de barrido: `grep -rcF` sobre un archivo unico antepone `ruta:` al conteo y produce falsos zombies. Usar `grep -cF` sin `-r`.
