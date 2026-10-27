# tacotios-claude-kit

Kit de Claude Code para llevarte a tu `~/.claude`: **98 skills, 37 agentes, 56 comandos** y unos pocos scripts. Es la parte portable de un ecosistema construido durante años; lo personal y lo confidencial no está aquí.

*English: a portable Claude Code kit (skills, agents, commands, helper scripts). Personal and business-specific material is excluded. Install is non-destructive.*

## Instalar

```bash
git clone https://github.com/tacotios-wq/tacotios-claude-kit.git
cd tacotios-claude-kit
./install.sh --dry-run   # muestra qué copiaría
./install.sh             # copia solo lo que te falte; nunca sobrescribe
```

Respeta `CLAUDE_CONFIG_DIR` si lo usas. No toca tu `CLAUDE.md`, `settings.json` ni hooks. Reinicia Claude Code después para que cargue lo nuevo.

## Lo más propio de este kit

- **`/95`** (`skills/95`): loop autónomo construir, auditar, autoprompt hasta cruzar un umbral de calidad medido, con puerta mecánica (`gate_95.py`) y frenos de presupuesto y estancamiento. Usa **Codex CLI** como auditor externo.
- **`/exponencial`**: hasta 3 ciclos (abrir, decidir, ejecutar, auditar con Codex, comprimir) donde el gate lo cierra un auditor real, nunca el mismo modelo que construyó.
- **`consigliere-adversarial`**: auditor adversarial de cualquier salida de un LLM; busca sesgos, omisiones y contrapuntos y emite veredicto sin suavizar.
- **`/fable`** (comando): protocolo de ocho reglas para tareas donde equivocarse cuesta (reformular, descomponer, tres alternativas, autocrítica, verificar en el mundo real).
- **`bin/codex_exec.py`**: envoltorio serializado de `codex exec` con lock y autotest.

`/95` y `/exponencial` requieren tener instalado y autenticado [Codex CLI](https://github.com/openai/codex). Sin él, no arrancan.

El resto (deep-research, agentes revisores por lenguaje, planificación, TDD, CRO, copywriting, video con Remotion y Manim, etc.) es contenido de la comunidad que se usa tal cual; mira `THIRD_PARTY.md`.

## Qué no incluye

Skills, agentes y scripts que dependen de datos, personas, proyectos o infraestructura privada de su autor. Algunas piezas pueden mencionar nombres de skills hermanas que no se publican; ignóralas o adáptalas.

## Licencia

MIT para el trabajo original (ver `LICENSE`). Cada pieza de terceros conserva su licencia (ver `THIRD_PARTY.md`).
