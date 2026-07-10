# Prototipos anteriores — AEM Questionnaire POC

---

## Prototipo 1

### Contexto

AEM (Asistencial Emergencia Móvil) es una empresa de salud prehospitalaria uruguaya. Cuando un socio llama por una emergencia, un operador telefónico conduce una entrevista estructurada para recolectar información clínica, detectar señales de alarma y clasificar el caso en tres niveles: Clave 1 (emergencia absoluta), Clave 2 (emergencia urgente) y Clave 3 (urgencia diferida).

Este prototipo es la primera implementación del microservicio, con un único cuadro clínico y arquitectura mínima.

### Arquitectura

**Stack:** Python + OpenAI GPT-4o. Sin frameworks ni base de datos.

En cada turno el modelo recibe: el system prompt con el comportamiento del asistente, el árbol del protocolo clínico, y el historial completo de la conversación. El modelo devuelve un JSON con seis campos:

```json
{
  "next_question": "...",
  "clave1_flag": false,
  "conversation_complete": false,
  "campos_recolectados": { "inicio": "...", "tipo_dolor": "...", ... },
  "reasoning": "...",
  "summary": null
}
```

El campo `campos_recolectados` usa exactamente las keys definidas en el system prompt, sin variaciones. El campo `reasoning` es un log interno imprimible en terminal durante las pruebas. La clasificación es **zero-shot**: el modelo clasifica aplicando su conocimiento médico general sobre los criterios del árbol, sin ejemplos de referencia calibrados con el criterio de AEM.

### Cuadros implementados

Un solo cuadro: `dolor_toracico` con 10 campos de protocolo. El cuadro se detecta por keyword matching — si el socio no menciona "pecho" o "tórax", no se carga ningún árbol.

### Escenarios probados

**Escenario A — Flujo completo hasta clasificación (Clave 2)**

Perfil ingresado: dolor opresivo hace una hora, intensidad 7, irradiación al brazo izquierdo, disnea leve, náuseas, consciente, habla normal, antecedente de hipertensión.

Resultado: clasificación Clave 2 con justificación correcta. En una primera variante con "sudo bastante" en lugar de "náuseas leves", el sistema clasificó Clave 1 — ver conclusiones.

**Escenario B — Corte por Clave 1 en tiempo real**

Perfil ingresado: dolor de 10 minutos; en el tercer turno el socio menciona espontáneamente dificultad respiratoria extrema y sensación de desmayo.

Resultado: el sistema interrumpió el cuestionario en ese turno e imprimió el mensaje de escalada. El campo `reasoning` registró: *"El paciente reporta dificultad respiratoria extrema y sensación de desmayo, lo cual son señales de Clave 1."*

**Escenario C — Respuestas evasivas**

El socio evadió la pregunta de localización dos veces consecutivas. El sistema reformuló la pregunta en el primer intento y registró el campo como "No precisado por el socio" en el segundo, continuando con el protocolo sin quedar atrapado.

### Conclusiones

**Los tres flujos principales funcionan correctamente.** El sistema completa el cuestionario, detecta Clave 1 en tiempo real y maneja respuestas evasivas según lo especificado.

**El sesgo conservador hacia Clave 1 es consistente con el principio de diseño.** El protocolo clínico de AEM trata los síntomas neurovegetativos como presencia/ausencia sin gradación; el modelo no tiene base para distinguir "sudo un poco" de "sudoración profusa" y ante la ambigüedad interpreta en la forma más grave. Este comportamiento es correcto por diseño: un falso positivo de Clave 1 (movilizar recursos innecesariamente) es preferible a un falso negativo. Esto valida la arquitectura híbrida planteada en el proyecto — el sistema clasifica los casos claros de forma autónoma y escala los casos ambiguos para que un humano decida.

**La clasificación zero-shot tiene limitaciones en casos borderline.** El modelo interpreta los criterios con su conocimiento médico general, que puede no coincidir con el criterio operacional de AEM.

### Limitaciones

- Un solo cuadro clínico implementado
- Detección del cuadro por keyword matching simple
- Clasificación zero-shot sin ejemplos calibrados con el criterio de AEM
- Sin validación de salida del modelo
- Sin persistencia ni interfaz de voz

---

## Prototipo 2

### Stack
- Python 3.11, OpenAI SDK 2.3, Pydantic 2.12
- Modelo: `gpt-4o-mini`
- Sin frameworks, sin base de datos, interfaz por terminal

### Cuadros clínicos implementados

| Cuadro | Archivo | Preguntas | Screening | Clasificación |
|---|---|---|---|---|
| Dolor torácico | `trees/dolor_toracico.json` | 13 | 2 preguntas | Few-shot |
| Fiebre | `trees/fiebre.json` | 8 | 2 preguntas | Clave 3 fija en código |
| Pérdida de conocimiento | `trees/perdida_de_conocimiento.json` | 8 | 1 pregunta | Few-shot |

### Flujo de ejecución

```
Saludo inicial
  → socio describe motivo de consulta
  → [LLAMADA 1] identify_cuadro() — identifica el cuadro contra catálogo trees/
      si confianza baja → muestra opciones, pide al socio que elija
  → carga tree JSON del cuadro identificado
  → run_screening() — preguntas sí/no en código puro, sin modelo
      si señal crítica → Clave 1 inmediata, fin
  → loop conversacional turno a turno
      [LLAMADA 2..N] call_model_validated() — una llamada por turno
          validación Pydantic estricta, hasta 3 reintentos por respuesta malformada
          modelo detecta Clave 1 en cada respuesta aunque no sea la pregunta correspondiente
          si clave1_flag → escalada inmediata, fin
  → cuestionario completo
      si cuadro == fiebre → Clave 3 directamente en código
      sino → [LLAMADA FINAL] classify_cuadro() — few-shot con 15-20 ejemplos
  → imprimir perfil clínico + clasificación
```

### Preguntas determinísticas por cuadro

| Cuadro | Pregunta | Dispara Clave 1 si |
|---|---|---|
| `dolor_toracico` | ¿Está consciente y puede responder? | responde NO |
| `dolor_toracico` | ¿Puede respirar con normalidad? | responde NO |
| `fiebre` | ¿Tiene convulsiones o está inconsciente? | responde SÍ |
| `fiebre` | ¿Tiene dificultad para respirar? | responde SÍ |
| `perdida_de_conocimiento` | ¿Está respirando en este momento? | responde NO |

### Schemas Pydantic

```python
TurnResponse           # next_question, clave1_flag, conversation_complete, campos_recolectados, reasoning
IdentificationResponse # cuadro_identificado, confianza, opciones, mensaje
ClassificationResponse # clasificacion, justificacion
```

### Estructura de archivos

```
main.py                  — orquestación del flujo completo
models.py                — schemas Pydantic
identifier.py            — identify_cuadro(): llamada independiente al modelo
classifier.py            — classify_cuadro(): llamada few-shot; fiebre retorna Clave 3 en código
deterministic.py         — run_screening(): preguntas sí/no sin modelo

trees/
  dolor_toracico.json
  fiebre.json
  perdida_de_conocimiento.json

prompts/
  system_prompt.txt
  identify_cuadro_prompt.txt
  classify_cuadro_prompt.txt

data/
  examples_dolor_toracico.json          — 15 ejemplos sintéticos Clave 1/2/3
  examples_perdida_de_conocimiento.json — 16 ejemplos sintéticos Clave 1/2/3
```

### Escenarios probados

**Escenario A — Dolor torácico, flujo completo (Clave 2)**

Perfil: dolor opresivo hacia la izquierda, inicio hace una hora, irradiación al brazo izquierdo, intensidad 6, náuseas, sin disnea, consciente, habla normal, antecedente de hipertensión.

Resultado: clasificación Clave 2. El modelo siguió la secuencia del árbol correctamente y recolectó los 14 campos sin inventar preguntas fuera del protocolo.

**Escenario B — Pérdida de conocimiento, Clave 1 detectada durante el cuestionario**

Perfil: motivo "se desmayó, está en el piso"; screening confirma que respira; durante el cuestionario el socio menciona espontáneamente "ahora dejó de responder, no reacciona a nada".

Resultado: el modelo activó `clave1_flag` y emitió el mensaje de escalada antes de continuar. Valida la detección de Clave 1 en tiempo real ante señales mencionadas fuera del orden del protocolo.

**Escenario C — Pérdida de conocimiento, flujo completo (Clave 2)**

Perfil: paciente recuperándose, responde con gemidos, contexto de ejercicio físico, antecedente de cardiopatía congénita.

Resultado: clasificación Clave 2. Sin el antecedente cardíaco el clasificador tendió a Clave 3 — los ejemplos few-shot de PDC no tenían cobertura de ese perfil.

### Cambios aplicados durante las sesiones de prueba

**1. Confianza media ya no avanza directamente**
`main.py / phase_identify()`: antes `"alta"` y `"media"` avanzaban sin mostrar nada al socio. Ahora solo `"alta"` avanza. Con `"media"` el modelo devuelve un mensaje de confirmación que se muestra al socio, y el loop continúa hasta llegar a `"alta"`.

**2. Señales universales de Clave 1 corregidas**
`prompts/system_prompt.txt`: se eliminó `"Paciente inconsciente o no responde a estímulos"` como señal universal. Reemplazado por criterios más precisos:
- "No respira, apnea o respiración agónica" (condición 1)
- "No respira Y no responde — paro cardiorrespiratorio" (condición 2)
- "El socio se está desmayando AHORA durante la llamada" (condición 5 — acotada a episodio en curso)
- Nota explícita: `"no responde a estímulos" con respiración confirmada NO es criterio universal de Clave 1`

Validado contra el manual de AEM: en PDC, `"respira + no responde a estímulos"` es Clave 2. El único criterio de Clave 1 universal en PDC es la apnea.

**3. Bug — mensaje de escalada no se mostraba**
`main.py / phase_questionnaire()`: el modelo podía activar `clave1_flag = true` pero poner una pregunta normal en `next_question`. El código imprimía `next_question` antes de chequear el flag, por lo que el mensaje de escalada nunca aparecía. Fix: chequear el flag antes de imprimir, y si está activo imprimir `ESCALADA_MSG` desde el código sin depender del modelo.

**4. Árbol PDC — nota explícita en pregunta de estímulos**
`trees/perdida_de_conocimiento.json`: agregada nota en `notas_clinicas` de la pregunta `respuesta_estimulos`: "que el paciente no responda a estímulos con respiración ya confirmada NO es criterio de Clave 1 en este cuadro."

**5. Árbol dolor torácico — alineación de nombres de campos**
`trees/dolor_toracico.json`: `estado_consciencia` → `consciencia` y `capacidad_habla` → `habla` en `secuencia_preguntas`, para coincidir con los nombres del `campos_schema`.

### Conclusiones

**El flujo completo funciona para dolor torácico.** Identificación, screening, cuestionario conversacional y clasificación few-shot funcionaron correctamente.

**El few-shot funciona para PDC con perfil adecuado.** La clasificación cambió de Clave 3 a Clave 2 al agregar antecedentes cardíacos, validando que el mecanismo few-shot está operativo en este cuadro.

**El modelo tiene sesgos de seguridad que superan las instrucciones del protocolo.** `gpt-4o-mini` tiene un sesgo conservador hacia Clave 1 ante síntomas que en su preentrenamiento están asociados a emergencias, independientemente de las instrucciones del system prompt. Este sesgo es problemático cuando el protocolo de AEM define explícitamente que esa situación es Clave 2. Este problema requiere trabajo de prompt engineering que corresponde al prototipo 3.

**El principio de diseño conservador tiene un límite operacional.** Si el sistema escala a Clave 1 en todos los casos de PDC con paciente que no responde, pierde utilidad para ese cuadro. El balance entre seguridad y precisión requiere calibración más fina.

### Limitaciones conocidas

- **El modelo activa Clave 1 por criterio propio en PDC:** ante combinaciones como "no responde + diabetes" o "no responde + sin recuperación", el modelo escala a Clave 1 aunque el manual lo clasifique como Clave 2. La corrección requiere trabajo de prompt engineering del prototipo 3.
- **Señales neurovegetativas sin gradación:** "palidez" mencionada por el socio puede disparar Clave 1 aunque sea leve. Los criterios universales no tienen gradación suficiente para que el modelo los aplique con precisión.
- **Ejemplos few-shot de PDC con cobertura incompleta:** `data/examples_perdida_de_conocimiento.json` no tiene ejemplos de PDC en esfuerzo físico sin antecedentes clasificados como Clave 2, lo que hace que el clasificador tienda a Clave 3 en esos perfiles.

---

## Prototipo 3 *(en curso — sección abierta a actualización)*

### Objetivos

El prototipo 3 abordó las limitaciones conocidas del prototipo 2 en tres líneas paralelas: reconstrucción formal de los árboles clínicos y los ejemplos few-shot usando el manual de AEM como fuente primaria; testing manual sistemático del flujo conversacional con corrección de bugs; y construcción de un set de test y pipeline de evaluación automatizado para el clasificador.

### Stack

Idéntico al prototipo 2: Python 3.11, OpenAI SDK, Pydantic 2.12, `gpt-4o-mini`, interfaz por terminal.

### Cuadros clínicos implementados

Los mismos tres cuadros del prototipo 2 (`dolor_toracico`, `fiebre`, `perdida_de_conocimiento`). No se agregaron cuadros nuevos.

### Reconstrucción formal del contenido clínico

Tanto los árboles como los ejemplos few-shot fueron reconstruidos usando un procedimiento validado contra el manual de AEM:

**Árboles clínicos (`trees/*.json`):** cada árbol fue reconstruido campo por campo — `preguntas_deterministas`, `campos_schema`, `secuencia_preguntas` y `criterios_clasificacion` — en un chat separado con el manual de AEM en contexto. La salida fue revisada y corregida contra el manual antes de ser committed. Cambios clave respecto al prototipo 2: bifurcación condicional en el screening de PDC (`condicion_activacion: "solo_si_inconsciente"` para la pregunta de respiración, que ahora se dispara solo cuando el paciente está confirmado inconsciente); notas clínicas explícitas en `notas_clinicas` para cada campo de pregunta; el árbol de PDC maneja dos instrucciones pre-llegada distintas según si el paciente inconsciente respira o no.

**Ejemplos few-shot (`data/examples/*.json`):** reconstruidos con un procedimiento estructurado diseñado para minimizar la contaminación entre el set de entrenamiento y el set de test. El set de dolor_toracico fue expandido a 21 ejemplos (desde 15 en el prototipo 2); el set de PDC fue reconstruido a 15 ejemplos. Ambos sets usan pares borderline — dos casos con perfil base idéntico que difieren en un solo campo clínico determinante — para enseñar al clasificador los bordes de decisión exactos en lugar de casos prototípicos.

### Reestructuración del directorio `data/`

`data/` fue dividido en dos subdirectorios para mantener físicamente separados los sets de entrenamiento y evaluación:

```
data/
  examples/
    examples_dolor_toracico.json          — 21 ejemplos few-shot Clave 1/2/3
    examples_perdida_de_conocimiento.json — 15 ejemplos few-shot Clave 2/3
  test_sets/
    test_set_dolor_toracico.json          — 20 casos de test
    test_set_perdida_de_conocimiento.json — 17 casos de test
```

`classifier.py` fue actualizado para cargar ejemplos desde `data/examples/`. `eval_classifier.py` fue actualizado para cargar test sets desde `data/test_sets/`.

### Cambios aplicados durante el testing del prototipo 3

**1. Mensaje de cierre neutral**
`main.py`: agregada constante `CIERRE_MSG` junto a `ESCALADA_MSG`. Cuando `conversation_complete = true` y `clave1_flag = false`, el código imprime `CIERRE_MSG` (tono neutro, sin señal de urgencia) en lugar del `next_question` generado por el modelo. Antes el modelo generaba un mensaje de cierre que reflejaba su evaluación clínica implícita del perfil — a veces con tono de escalada — porque la instrucción en el system prompt era vaga ("mensaje de cierre amable"). La instrucción en `system_prompt.txt` también fue actualizada para indicar explícitamente que el cierre debe ser neutral y que la clasificación ocurre en un paso posterior separado.

**2. Screening PDC — segunda pregunta condicional**
`deterministic.py`: la segunda pregunta de screening del árbol de PDC ("¿Está respirando en este momento?") ahora tiene `condicion_activacion: "solo_si_inconsciente"`. Cuando el paciente está confirmado consciente en la primera pregunta, `run_screening()` omite la pregunta de respiración completamente. Cuando está confirmado inconsciente, la segunda pregunta se dispara y el árbol define dos instrucciones pre-llegada distintas: posición de seguridad (respira) o iniciar RCP (no respira). Ambas ramas retornan Clave 1.

**3. Respuestas inconexas en el loop conversacional**
`prompts/system_prompt.txt`: agregada una segunda subsección al bloque de manejo de respuestas, separada de la lógica de respuestas evasivas existente. Cuando la respuesta del socio no corresponde a ningún campo del schema (por ejemplo, pregunta "¿cuánto tarda la ambulancia?"), el modelo responde brevemente si es razonable y retoma inmediatamente la pregunta activa, sin marcar ningún campo como cubierto y sin contabilizar el intercambio como intento de la lógica de evasivas.

**4. Parámetro opcional de ejemplos en el clasificador**
`classifier.py`: `classify_cuadro()` acepta ahora un parámetro opcional `examples: list | None = None`. Si es `None`, carga los ejemplos desde `data/examples/` como antes. Si se pasa una lista vacía, el clasificador corre en modo zero-shot. Esto habilitó la comparación few-shot vs zero-shot en el script de evaluación.

**5. Script de evaluación — modo de comparación zero-shot**
`eval_classifier.py`: agregado flag `--zero-shot`. Cuando se activa, el script corre el test set completo dos veces — una con ejemplos few-shot y otra con lista vacía — e imprime ambos resultados con una tabla comparativa. Corregidos problemas de encoding en consola Windows (reemplazados caracteres Unicode por equivalentes ASCII). La salida JSON en modo `--zero-shot` genera dos archivos separados: `*_few_shot.json` y `*_zero_shot.json`.

### Construcción del set de test

Los sets de test fueron construidos en una sesión dedicada con un procedimiento formal independiente de la construcción de los ejemplos few-shot. Cada caso fue verificado contra dos criterios antes de su inclusión: alineación de keys con el `campos_schema` del árbol correspondiente (encastre), e independencia respecto a todos los ejemplos few-shot — ningún caso de test puede coincidir con ningún ejemplo few-shot en todos los campos clínicos determinantes para su frontera de clasificación.

- `test_set_dolor_toracico.json`: 20 casos (5 Clave 1, 10 Clave 2, 5 Clave 3). Incluye pares borderline en ambas fronteras Clave 1/2 y Clave 2/3.
- `test_set_perdida_de_conocimiento.json`: 17 casos (0 Clave 1, 10 Clave 2, 7 Clave 3). Los casos Clave 1 son manejados por el screening determinístico y nunca llegan al clasificador.

### Primera corrida de evaluación *(preliminar — se espera que cambie)*

Corrida el 15/06/2026. 37 casos en total, sin errores de API.

**Few-shot:**

| Cuadro | Accuracy | Subtriage | Sobre-triage |
|---|---|---|---|
| dolor_toracico | 85,0% | 15,0% (3 casos) | 0,0% |
| perdida_de_conocimiento | 82,4% | 5,9% (1 caso) | 11,8% (2 casos) |
| **Global** | **83,8%** | **10,8% (4 casos)** | **5,4% (2 casos)** |

Sin subtriage fatal (Clave 1 esperada, clase inferior obtenida).

**Zero-shot:**

| Cuadro | Accuracy | Subtriage | Sobre-triage |
|---|---|---|---|
| dolor_toracico | 100,0% | 0,0% | 0,0% |
| perdida_de_conocimiento | 82,4% | 11,8% (2 casos) | 5,9% (1 caso) |
| **Global** | **91,9%** | **5,4% (2 casos)** | **2,7% (1 caso)** |

Sin subtriage fatal en ninguno de los dos modos.

**Interpretación:** el zero-shot superó al few-shot globalmente, impulsado completamente por dolor_toracico (100% vs 85%). Los tres errores few-shot en dolor_toracico comparten un patrón común: perfiles Clave 2 donde el único criterio discriminante son factores de riesgo cardiovascular en antecedentes, sin irradiación ni síntomas neurovegetativos. Los ejemplos few-shot no tienen cobertura suficiente de este subtipo y el modelo aprende una regla espuria (sin irradiación + sin neurovegetativos → Clave 3) de ejemplos cercanos. El zero-shot cae en el conocimiento clínico general del modelo, que maneja este subtipo correctamente. Para PDC, ambos modos producen el mismo accuracy (82,4%) pero con distribuciones de error distintas — el few-shot reduce el sobre-triage en casos con movimientos anormales y cianosis, pero introduce subtriage en otros dos casos. El caso PDC #3 (PDC espontánea sin contexto explicativo en paciente joven → Clave 2) falla en ambos modos.

La conclusión no es abandonar el few-shot — el enfoque es necesario para anclar el clasificador a los criterios específicos de AEM en lugar de depender del conocimiento clínico general del modelo. El trabajo pendiente es cerrar los gaps de cobertura identificados: agregar ejemplos Clave 2 para dolor_toracico donde los antecedentes son el único criterio discriminante sin irradiación ni neurovegetativos; y agregar un ejemplo de PDC que modele explícitamente el criterio "sin contexto explicativo → Clave 2 aunque el paciente esté recuperado y asintomático".

### Limitaciones conocidas *(al cierre de la primera corrida)*

- **Gap few-shot dolor_toracico — Clave 2 solo por antecedentes:** tres casos del set de test donde los factores de riesgo cardiovascular son el único criterio Clave 2 (sin irradiación, sin neurovegetativos) son mal clasificados como Clave 3 bajo few-shot. Los ejemplos existentes no modelan este subtipo.
- **Gap few-shot PDC — ausencia de contexto explicativo:** el caso PDC sin contexto explicativo en paciente joven recuperado (Clave 2 según el manual de AEM) es mal clasificado como Clave 3 en ambos modos. El criterio ("ausencia de causa aparente requiere evaluación urgente") no está representado en los ejemplos actuales.
- **Sobre-triage PDC en señales intra-episodio:** el few-shot lleva al clasificador a escalar a Clave 1 cuando se observaron movimientos anormales o cianosis durante el episodio, aunque el árbol de AEM los clasifica como Clave 2. El zero-shot los maneja correctamente.
- **Flujo conversacional no evaluado end-to-end:** el pipeline de evaluación testea el clasificador en aislamiento (perfil pre-armado → clasificación). La evaluación end-to-end completa — paciente simulado genera respuestas turno a turno, el sistema conduce el cuestionario, clasificación final comparada contra la esperada — no está implementada. El flujo de `main.py` está acoplado a llamadas bloqueantes a `input()` y requeriría refactoring para ser manejado por un script externo turno a turno.
