# Experimento 02 — Validación del Prototipo 2

## Contexto

El prototipo 2 extiende el prototipo 1 en cuatro dimensiones: identificación del cuadro por LLM en lugar de keyword matching, clasificación few-shot en llamada separada, screening determinístico previo al cuestionario, y soporte para múltiples cuadros clínicos. Este experimento valida el flujo completo del prototipo 2 a través de pruebas manuales sobre los tres cuadros implementados.

---

## Qué se buscaba probar

1. Que el identificador maneje correctamente descripciones con confianza alta, media y baja
2. Que el screening determinístico escale a Clave 1 cuando corresponde sin llamar al modelo
3. Que el cuestionario conversacional detecte Clave 1 en tiempo real durante la conversación
4. Que la clasificación few-shot funcione correctamente para cuadros distintos al dolor torácico
5. Que el flujo completo llegue al perfil clínico y clasificación final sin romperse

---

## Escenarios probados

### Escenario A — Dolor torácico, flujo completo hasta clasificación (Clave 2)

**Perfil ingresado:**
```
Motivo: me duele el pecho, siento como una presión
Screening: consciente sí, respira sí
Inicio: hace una hora / Tipo: presión / Intensidad: 6
Localización: hacia la izquierda / Irradiación: brazo izquierdo
Evolución: intermitente / Actividad previa: subiendo las escaleras
Palpitaciones: no / Disnea: no / Neurovegetativos: náuseas
Consciencia: consciente sin mareos / Habla: normal
Antecedentes: hipertensión
```

**Resultado:**
```
Clasificación: Clave 2
Justificación: Dolor opresivo en el lado izquierdo con irradiación al brazo izquierdo,
inicio durante esfuerzo (subiendo escaleras) y náuseas presentes. Intensidad moderada (6/10),
consciente y habla con normalidad. Antecedente de hipertensión como factor de riesgo cardiovascular.
```

**Observación:** el modelo siguió la secuencia del árbol correctamente y recolectó los 14 campos (2 del screening + 12 conversacionales) sin inventar preguntas fuera del protocolo.

---

### Escenario B — Pérdida de conocimiento, Clave 1 detectada durante el cuestionario

**Perfil ingresado:**
```
Motivo: se desmayó, está en el piso
Screening: respira sí
Primera pregunta: responde a estímulos sí
[durante el cuestionario] "espere, ahora dejó de responder, no reacciona a nada"
```

**Resultado:** el modelo activó `clave1_flag` y emitió el mensaje de escalada antes de continuar el cuestionario.

**Observación:** valida la detección de Clave 1 en tiempo real ante señales mencionadas espontáneamente por el socio fuera del orden del protocolo.

---

### Escenario C — Pérdida de conocimiento, flujo completo hasta clasificación (Clave 2)

**Perfil ingresado:**
```
Motivo: mi hijo se desmayó
Screening: respira sí
Responde a estímulos: sí, con gemidos
Movimientos anormales: no / Color: normal
Contexto: haciendo ejercicio / Estrés previo: no
Antecedentes: cardiopatía congénita
TEC: no / Recuperación: abriendo los ojos y responde
```

**Resultado:**
```
Clasificación: Clave 2
Justificación: Antecedentes de cardiopatía congénita, PDC durante esfuerzo físico,
sin recuperación completa. Requiere atención urgente.
```

**Observación:** confirma que el clasificador few-shot funciona para PDC. Sin el antecedente cardíaco el modelo clasificó Clave 3 — los ejemplos del archivo no tienen cobertura suficiente de PDC en esfuerzo sin antecedentes.

---

## Bugs encontrados y corregidos durante el experimento

### Bug 1 — Confianza media avanzaba sin confirmar con el socio

**Síntoma:** con confianza `"media"` el flujo cargaba el árbol directamente sin mostrar el mensaje de confirmación que el modelo había generado.

**Causa:** `phase_identify()` trataba `"alta"` y `"media"` de forma idéntica.

**Fix:** solo `"alta"` avanza. Con `"media"` o `"baja"` el mensaje se muestra al socio y el loop continúa.

---

### Bug 2 — Mensaje de escalada no aparecía en pantalla

**Síntoma:** el modelo activaba `clave1_flag = true` pero en `next_question` ponía una pregunta normal. El código imprimía `next_question` antes de chequear el flag, por lo que el programa terminaba sin mostrar el mensaje de escalada.

**Causa:** el modelo no respetaba la instrucción del system prompt que dice que cuando `clave1_flag = true` el `next_question` debe ser el mensaje de escalada.

**Fix:** en `phase_questionnaire()` se chequea el flag antes de imprimir. Si está activo se imprime `ESCALADA_MSG` desde el código, sin depender de lo que el modelo ponga en `next_question`.

---

### Bug 3 — Inconsistencia de nombres de campos en árbol de dolor torácico

**Síntoma:** en `secuencia_preguntas` los campos se llamaban `estado_consciencia` y `capacidad_habla`, pero en `campos_schema` se llamaban `consciencia` y `habla`. El modelo podía guardar el campo con el nombre incorrecto.

**Fix:** alineados los nombres en `secuencia_preguntas` con los del `campos_schema`.

---

## Cambios al system prompt validados contra el manual de AEM

La lista de señales universales de Clave 1 tenía una condición demasiado amplia: `"Paciente inconsciente o no responde a estímulos"`. Esta condición hacía que el modelo escalara a Clave 1 en todos los casos de PDC donde el socio reportaba que el paciente no respondía, aunque la respiración estuviera confirmada.

Validado contra el manual: en PDC, `"respira + no responde a estímulos"` es **Clave 2**, no Clave 1. El único criterio de Clave 1 universal en PDC es la apnea.

**Cambios aplicados:**
- Se eliminó `"no responde a estímulos"` como criterio universal independiente
- Se separó `"no respira"` (condición 1) de `"no respira Y no responde — paro cardiorrespiratorio"` (condición 2)
- La condición de síncope durante la llamada se acotó a episodio en curso, no previo
- Se agregó nota explícita: `"no responde a estímulos con respiración confirmada NO es criterio universal de Clave 1"`
- Se agregó nota en el árbol de PDC en la pregunta de estímulos para reforzar la instrucción en contexto

---

## Limitaciones identificadas

### 1. El modelo activa Clave 1 por criterio propio en PDC

A pesar de las correcciones al system prompt, el modelo continuó escalando a Clave 1 en perfiles de PDC que el manual clasifica como Clave 2. El patrón observado: el modelo combina `"no responde a estímulos"` con otros factores de riesgo (diabetes, sin recuperación) y escala por razonamiento médico propio, ignorando las instrucciones del protocolo.

El manual es explícito: si respira → máximo Clave 2 en PDC. La corrección requiere trabajo de prompt engineering más profundo, probablemente separar la detección de Clave 1 del loop conversacional para este cuadro.

**Impacto:** no se pudo validar el flujo completo de PDC hasta clasificación few-shot con un perfil de "no responde + sin recuperación". Se usó un perfil con recuperación parcial para llegar a la clasificación.

### 2. Señales neurovegetativas sin gradación suficiente

"Palidez" mencionada por el socio disparó Clave 1 aunque el criterio universal dice "palidez extrema". El modelo no tiene base para distinguir palidez leve de extrema sin gradación explícita en el protocolo.

### 3. Ejemplos few-shot de PDC con cobertura incompleta

El archivo `data/examples_perdida_de_conocimiento.json` no tiene ejemplos de PDC en esfuerzo físico sin antecedentes clasificados como Clave 2. Sin ese ejemplo el clasificador tiende a Clave 3 para ese perfil. Se requieren ejemplos adicionales validados con el manual.

---

## Conclusiones

### 1. El flujo completo del prototipo 2 funciona para dolor torácico

Identificación, screening, cuestionario conversacional y clasificación few-shot funcionaron correctamente. El perfil clínico generado es coherente con los datos recolectados y la clasificación Clave 2 es correcta.

### 2. El few-shot funciona para PDC con perfil adecuado

Se confirmó que el clasificador usa los ejemplos de referencia para PDC. La clasificación cambió de Clave 3 a Clave 2 al agregar antecedentes cardíacos, lo que valida que el mecanismo few-shot está operativo en este cuadro.

### 3. El modelo tiene sesgos de seguridad que superan las instrucciones del protocolo

`gpt-4o-mini` tiene un sesgo conservador hacia Clave 1 ante síntomas que en su preentrenamiento están asociados a emergencias, independientemente de las instrucciones del system prompt. Este sesgo es problemático cuando el protocolo de AEM define explícitamente que esa situación es Clave 2. La arquitectura del prototipo 3 debería considerar separar la detección de Clave 1 del modelo conversacional.

### 4. El principio de diseño conservador tiene un límite operacional

El sesgo hacia Clave 1 es aceptable como principio general, pero si el sistema escala a Clave 1 en todos los casos de PDC con paciente que no responde, pierde utilidad para ese cuadro. El balance entre seguridad y precisión requiere más trabajo de calibración.
