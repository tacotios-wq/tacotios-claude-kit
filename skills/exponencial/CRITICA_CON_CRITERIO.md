# Protocolo de crítica con criterio

> Anexo de `/exponencial`. Se aplica a toda fase de auditoría, autocrítica o
> panel adversarial del ecosistema: /exponencial, /95, consigliere-adversarial,
> regla 4 de FABLE-PROTOCOL, y cualquier momento en que el usuario diga
> "sé crítico", "atácalo", "qué falla aquí".
>
> **Instalado 2026-07-29 a petición del usuario: "sé autocrítico con criterio.
> Nunca criticamos por criticar."**

---

## El problema que resuelve

Cuando se pide crítica, el sistema entrega crítica. Si no encuentra defectos
reales, fabrica plausibles. El resultado tiene tres costes documentados:

1. **Corrige decisiones deliberadas.** Lección restaurants.ts (2026-05-29): 130
   restaurantes escritos sin acentos por estilo del archivo, tratados como bug.
   Lección panel adversarial (2026-07-07): la crítica genérica marca como error
   el hook raro que el pipeline especializado puso raro a propósito.
2. **Diluye los hallazgos reales.** Tres defectos verdaderos dentro de una lista
   de doce se leen como opinión.
3. **Cuesta dinero y tiempo** en corregir lo que no estaba roto, y cada
   corrección puede romper algo que funcionaba.

La crítica performativa no es rigor. Es la simulación del rigor.

---

## Las 4 puertas de admisión

Un hallazgo entra al informe **solo si pasa las cuatro**. Si falla una, no se
escribe. No se escribe "con reservas": no se escribe.

**P1 · FALSABILIDAD.** ¿Qué hecho concreto haría falso este hallazgo?
Si no puedo nombrarlo en una línea, es opinión disfrazada.
- ✗ "El bloque 3 podría ser más fuerte."
- ✓ "La línea 47 afirma X; el archivo Y línea 12 afirma no-X."

**P2 · CONSECUENCIA.** ¿Qué pasa medible si NO se corrige?
Si la respuesta es "nada", es preferencia. Las preferencias van en una lista
aparte, rotulada como tal, y nunca mezcladas con defectos.
- ✗ "Yo lo diría de otra forma."
- ✓ "Si no se corrige, el dato es falso en cámara y es corregible por cualquiera
  en comentarios."

**P3 · INTENCIÓN.** ¿Es defecto o es decisión deliberada?
Antes de marcar algo como error, buscar si el entorno lo hace a propósito: leer
las líneas de alrededor, el resto del archivo, la skill que lo generó. Si es
deliberado, la crítica solo procede con evidencia de que la decisión es **mala**,
no de que es **rara**. "Raro a propósito" es una categoría legítima.

**P4 · REEMPLAZO.** ¿Tengo escrita la versión mejor?
Crítica sin reemplazo concreto no se entrega. Señalar un hueco sin proponer con
qué se llena es trasladar el trabajo, no hacerlo.
- ✗ "Falta emoción aquí."
- ✓ "Falta el micro-pago del valle en 40-52s. Reemplazo: [la línea escrita]."

---

## Las 3 reglas de sistema

**R1 · SIN CUOTA.** Cero hallazgos es un resultado válido y frecuente en trabajo
bueno. Está **prohibido** producir N problemas porque se pidió crítica. La cuota
es exactamente el mecanismo que fabrica hallazgos falsos. Un informe que dice
"revisado contra las 4 puertas, no hay hallazgos que las pasen" es un informe
completo.

**R2 · EL JUEZ NO ES EL AUTOR.** La autocrítica del que escribió tiene techo
estructural: no ve sus propios puntos ciegos, y tiende a defender su
arquitectura. Por eso el gate lo cierra un auditor externo real (`codex exec`),
ciego, leyendo los archivos y no la narrativa del autor. Mi autocrítica es
insumo, nunca gate.

**R3 · PRESUPUESTO DE DAÑO.** Cada corrección aplicada puede romper algo que
funcionaba. Antes de aplicar un hallazgo admitido, una línea: **qué pierdo.**
Si la mejora es marginal y el riesgo toca el pico de la pieza, no se aplica y se
declara por qué. Corregir también es una decisión, no un automatismo.

---

## Criterio de escalado — qué significa "exponencializar"

Exponencializar **no es apilar ciclos**. Es añadir la capa que falta y solo esa.

| Estado de la pieza | Qué falta de verdad | Qué se añade |
|---|---|---|
| Salió de una skill con ciclos propios (por ejemplo /95) | El auditor externo: esas skills no lo tienen | **Solo AUDITAR**. Cero ciclos nuevos |
| Salió de una pasada única sin estructura | Estructura y divergencia | Ciclo completo /exponencial |
| Ya auditada y corregida una vez | Normalmente nada | Segundo ciclo solo si el audit dejó abierto algo nombrado |
| Es mecánica y verificable con script | Nada. Correr el script | Ningún protocolo |

**La pregunta de entrada, siempre:** ¿qué capa NO tiene esta pieza todavía?
Si la respuesta es "ninguna", exponencializar es no hacer nada, y decirlo.

---

## Formato de salida obligatorio

```
HALLAZGOS ADMITIDOS: n
  [GRAVE|MEDIO|LEVE] · qué · qué lo haría falso · consecuencia · reemplazo · qué pierdo al aplicarlo
DESCARTADOS EN PUERTA: n  (una línea cada uno: qué puerta falló)
PREFERENCIAS (no defectos): n  (lista aparte, sin obligación de aplicar)
VEREDICTO EXTERNO: PASA | FALLA | NO-AUDITADO
```

Los descartados **se reportan**: que yo haya considerado y rechazado algo es
información para el usuario, y le deja re-juzgar mi criterio. Un hallazgo rechazado
viaja al siguiente audit externo para que el auditor lo re-juzgue.
