---
description: Control de calidad del ultimo output o de un archivo especifico
allowed-tools: Read, Glob, Grep, WebSearch, Task
argument-hint: [archivo a revisar (opcional)]
---

Delega al agente @reviewer.

Si se dio un archivo: revisa "$ARGUMENTS". Si no, revisa el ultimo output de esta sesion. Evalua en 5 dimensiones (cumplimiento, precision, claridad, redaccion, valor), puntuacion X/10, problemas con correccion propuesta, y veredicto final.
