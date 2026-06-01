# AEM Questionnaire POC

Microservicio de triaje clínico conversacional por terminal, desarrollado como parte de una tesis académica para AEM (Asistencial Emergencia Móvil), empresa de salud prehospitalaria uruguaya.

El sistema replica el rol de un operador telefónico de emergencias: conduce una entrevista clínica estructurada con el socio (paciente o familiar), detecta señales de emergencia en tiempo real y clasifica la urgencia al finalizar.

## Sistema de clasificación AEM

- **Clave 1** — Emergencia absoluta. Requiere respuesta inmediata. El sistema escala sin completar el cuestionario.
- **Clave 2** — Emergencia urgente. Requiere respuesta rápida. Se asigna al finalizar el cuestionario.
- **Clave 3** — Urgencia diferida. Requiere evaluación médica programada.

---

## Prototipo 1 — antecedente

El primer prototipo implementó un único cuadro clínico (`dolor_toracico`) con:
- Keyword matching para detectar el cuadro a partir de la primera respuesta del socio
- Una sola llamada al modelo por turno que conducía el cuestionario y clasificaba al final
- Clasificación zero-shot incluida en la misma llamada del cuestionario
- Sin validación de salida del modelo

---

## Cambios aplicados durante las sesiones de prueba (sobre prototipo 2 base)

### 1. Identificación — confianza media ya no avanza directamente
`main.py / phase_identify()`: antes `"alta"` y `"media"` avanzaban sin mostrar nada al socio. Ahora solo `"alta"` avanza. Con `"media"` el modelo devuelve un mensaje de confirmación que se muestra al socio, y el loop continúa hasta llegar a `"alta"`.

### 2. System prompt — señales universales de Clave 1 corregidas
`prompts/system_prompt.txt`: se eliminó `"Paciente inconsciente o no responde a estímulos"` como señal universal. Se reemplazó por criterios más precisos:
- "No respira, apnea o respiración agónica" (condición 1)
- "No respira Y no responde a estímulos — paro cardiorrespiratorio" (condición 2)
- "El socio se está desmayando AHORA durante la llamada" (condición 5 — acotada a episodio en curso, no previo)
- Nota explícita: `"no responde a estímulos" con respiración confirmada NO es criterio universal de Clave 1`

Validado contra manual de AEM: "no respira" es el único criterio de Clave 1 universal en PDC.

### 3. Bug — mensaje de escalada no se mostraba
`main.py / phase_questionnaire()`: el modelo podía activar `clave1_flag = true` pero poner una pregunta normal en `next_question`. El código imprimía `next_question` antes de chequear el flag, por lo que el mensaje de escalada nunca aparecía. Fix: chequear el flag antes de imprimir, y si está activo imprimir `ESCALADA_MSG` directo desde el código sin depender del modelo.

### 4. Árbol PDC — nota explícita en pregunta de estímulos
`trees/perdida_de_conocimiento.json`: agregada nota en `notas_clinicas` de la pregunta `respuesta_estimulos`: "que el paciente no responda a estímulos con respiración ya confirmada NO es criterio de Clave 1 en este cuadro — es la presentación esperada de PDC."

### 5. Árbol dolor torácico — alineación de nombres de campos
`trees/dolor_toracico.json`: `estado_consciencia` → `consciencia` y `capacidad_habla` → `habla` en `secuencia_preguntas`, para coincidir con los nombres del `campos_schema`.

---

## Limitaciones conocidas del prototipo 2

- **El modelo activa Clave 1 por criterio propio en PDC:** ante combinaciones como "no responde + diabetes" o "no responde + sin recuperación", el modelo escala a Clave 1 aunque el manual de AEM lo clasifique como Clave 2. El criterio correcto es: en PDC, si respira → máximo Clave 2. La corrección requiere trabajo de prompt engineering que corresponde al prototipo 3.
- **Señales neurovegetativas sin gradación:** "palidez" mencionada por el socio puede disparar Clave 1 aunque sea leve. Los criterios universales ("palidez extrema", "sudoración profusa") no tienen gradación suficiente para que el modelo los aplique con precisión.
- **Ejemplos few-shot de PDC sin cobertura de esfuerzo físico:** el archivo `data/examples_perdida_de_conocimiento.json` no tiene ejemplos con contexto de esfuerzo físico clasificados como Clave 2, lo que hace que el clasificador tienda a Clave 3 en esos perfiles sin antecedentes de riesgo.

---

## Prototipo 2 — estructura actual

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

Las preguntas determinísticas se definen en cada tree JSON (`preguntas_deterministas`) y las evalúa `deterministic.py` en código puro. Solo disparan Clave 1 si la respuesta específica lo indica.

| Cuadro | Pregunta | Dispara Clave 1 si |
|---|---|---|
| `dolor_toracico` | ¿Está consciente y puede responder? | responde NO |
| `dolor_toracico` | ¿Puede respirar con normalidad? | responde NO |
| `fiebre` | ¿Tiene convulsiones o está inconsciente? | responde SÍ |
| `fiebre` | ¿Tiene dificultad para respirar? | responde SÍ |
| `perdida_de_conocimiento` | ¿Está respirando en este momento? | responde NO |

Para PDC: "no respira" = Clave 1. "Respira pero no responde a estímulos" = entra al cuestionario conversacional, clasificación probable Clave 2.

### Estructura de archivos

```
main.py                  — orquestación del flujo completo
models.py                — schemas Pydantic: TurnResponse, IdentificationResponse, ClassificationResponse
identifier.py            — identify_cuadro(): llamada independiente al modelo
classifier.py            — classify_cuadro(): llamada few-shot; fiebre retorna Clave 3 en código
deterministic.py         — run_screening(): preguntas sí/no sin modelo

trees/
  dolor_toracico.json          — árbol clínico con campos_schema y preguntas_deterministas
  fiebre.json                  — árbol clínico, clasificacion_fija: "Clave 3"
  perdida_de_conocimiento.json — árbol clínico con bifurcación respiración/estímulos

prompts/
  system_prompt.txt            — prompt base genérico con placeholder {{campos_schema}}
  identify_cuadro_prompt.txt   — prompt para la llamada de identificación
  classify_cuadro_prompt.txt   — prompt para la llamada de clasificación few-shot

data/
  examples_dolor_toracico.json          — 15 ejemplos sintéticos Clave 1/2/3
  examples_perdida_de_conocimiento.json — 16 ejemplos sintéticos Clave 1/2/3
```

### Estructura del tree JSON

Cada `trees/*.json` tiene esta estructura:

```json
{
  "cuadro": "nombre_del_cuadro",
  "descripcion": "descripción para el catálogo de identificación",
  "clasificacion_fija": "Clave 3",        // solo si aplica (fiebre)
  "preguntas_deterministas": [...],        // preguntas sí/no de screening
  "campos_schema": { "campo": "descripción" },  // define las keys de campos_recolectados
  "secuencia_preguntas": [...],            // preguntas para el modelo
  "criterios_clasificacion": { ... }      // criterios Clave 1/2/3 para el clasificador
}
```

El `campos_schema` es inyectado dinámicamente en `system_prompt.txt` via `build_system_message()`, reemplazando el placeholder `{{campos_schema}}`. El modelo usa exactamente esas keys en `campos_recolectados`.

### Schemas Pydantic

```python
TurnResponse           # next_question, clave1_flag, conversation_complete, campos_recolectados, reasoning
IdentificationResponse # cuadro_identificado, confianza, opciones, mensaje
ClassificationResponse # clasificacion, justificacion
```

### Cómo correr

```bash
pip install -r requirements.txt
# configurar OPENAI_API_KEY en .env
python main.py
```

---

## Contenido clínico — procedimiento de validación

El modelo no tiene acceso al manual de mesa central de AEM. El flujo validado para contenido clínico es:

1. Claude Code genera la estructura (árboles, ejemplos, criterios)
2. Un chat separado con el manual de AEM revisa y corrige el contenido
3. El contenido corregido se reemplaza en este repo

Archivos que requieren validación contra el manual ante cualquier cambio de contenido:
- `trees/*.json` — preguntas, criterios, preguntas determinísticas
- `data/examples_*.json` — casos sintéticos de clasificación
