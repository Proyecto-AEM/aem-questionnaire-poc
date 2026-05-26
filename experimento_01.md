# Experimento 01 — Prototipo de Cuestionario Clínico Conversacional

## Contexto

AEM (Asistencial Emergencia Móvil) es una empresa de salud prehospitalaria uruguaya. Cuando un socio llama por una emergencia, un operador telefónico conduce una entrevista estructurada para recolectar información clínica, detectar señales de alarma y clasificar el caso en tres niveles de prioridad: Clave 1 (emergencia absoluta), Clave 2 (emergencia urgente) y Clave 3 (urgencia diferida).

Este experimento es el primer prototipo de un microservicio que automatiza ese rol mediante un modelo de lenguaje. El objetivo no es reemplazar al operador sino explorar si un LLM puede conducir el protocolo de forma confiable, detectar señales críticas en tiempo real y producir un resumen clínico estructurado como salida.

---

## Qué se buscaba probar

1. Que el sistema pueda conducir una conversación clínica turno a turno siguiendo el protocolo de AEM para el cuadro de dolor torácico
2. Que detecte señales de Clave 1 en cualquier momento de la conversación, incluso cuando el socio las menciona espontáneamente fuera del orden del protocolo
3. Que maneje respuestas evasivas o no relacionadas sin quedarse trabado
4. Que genere un resumen clínico estructurado con clasificación preliminar al finalizar el cuestionario

---

## Arquitectura del prototipo

**Stack:** Python + OpenAI GPT-4o. Sin frameworks ni base de datos.

En cada turno el modelo recibe tres cosas:

- **System prompt** (`prompts/system_prompt.txt`): define el comportamiento del asistente — una pregunta por turno, tono empático, no emitir diagnósticos, detectar Clave 1 en todo momento, manejar respuestas evasivas con hasta dos reintentos antes de registrar el campo como "No precisado por el socio"
- **Árbol de protocolo** (`trees/dolor_toracico.json`): las 10 preguntas del protocolo clínico con su propósito, notas clínicas y criterios de clasificación para Clave 1, 2 y 3
- **Historial completo** de la conversación hasta ese turno

El modelo devuelve en cada turno un JSON con seis campos: la pregunta a hacerle al socio en ese turno; un flag de Clave 1 que se activa si detectó una señal crítica; un flag que indica si el cuestionario ya está completo; un diccionario con los campos clínicos recolectados hasta ese punto, acumulados turno a turno; una línea de razonamiento interno; y el resumen clínico final, que viene vacío en todos los turnos intermedios y solo se completa cuando el cuestionario termina.

```json
{
  "next_question": "...",
  "clave1_flag": false,
  "conversation_complete": false,
  "campos_recolectados": {
    "inicio": "...",
    "tipo_dolor": "...",
    "intensidad": "...",
    "localizacion": "...",
    "irradiacion": "...",
    "disnea": "...",
    "neurovegetativos": "...",
    "consciencia": "...",
    "habla": "...",
    "antecedentes": "..."
  },
  "reasoning": "...",
  "summary": null
}
```

El campo `campos_recolectados` usa exactamente estas diez keys, fijadas en el system prompt, sin variaciones. Solo se incluyen los campos ya cubiertos en la conversación hasta ese turno y se acumulan turno a turno. Cuando el cuestionario termina, el código captura este campo del último turno para usarlo como input del clasificador.

El campo `reasoning` es un log interno que el sistema imprime en terminal durante las pruebas y se puede desactivar en producción.

**Clasificación en este prototipo:** zero-shot. El modelo clasifica el caso aplicando su conocimiento médico general sobre los criterios definidos en el árbol, sin haber visto ejemplos previos de clasificaciones reales de AEM. Esto implica que ante casos ambiguos — donde los criterios del árbol no alcanzan para resolver la clasificación de forma determinista — el modelo recurre al conocimiento adquirido durante su preentrenamiento, conocimiento que no está calibrado con el criterio operacional específico de AEM y puede divergir de él. Esta limitación se aborda en la conclusión 3.

---

## Campos del protocolo de dolor torácico

| # | Campo | Pregunta guía |
|---|-------|---------------|
| 1 | Inicio | ¿Hace cuánto tiempo comenzó el dolor? |
| 2 | Tipo de dolor | ¿Presión, quemadura, puntada? |
| 3 | Intensidad | Escala 1-10 |
| 4 | Localización | ¿Dónde exactamente? |
| 5 | Irradiación | ¿Se corre al brazo, mandíbula, espalda? |
| 6 | Disnea | ¿Dificultad para respirar? |
| 7 | Neurovegetativos | ¿Náuseas, vómitos, sudoración, mareos? |
| 8 | Estado de consciencia | ¿Consciente? ¿Riesgo de síncope? |
| 9 | Capacidad de habla | ¿Puede hablar con normalidad? |
| 10 | Antecedentes cardiovasculares | ¿HTA, DBT, cardiopatía previa? |

---

## Escenarios probados

### Escenario A — Flujo completo hasta resumen (Clave 2)

**Objetivo:** verificar que el sistema complete el cuestionario y genere un resumen con clasificación correcta ante un perfil típico de Clave 2.

**Entradas utilizadas:**
```
me duele el pecho / hace una hora / es como una presión / 7 /
en el centro del pecho / sí, se corre al brazo izquierdo /
sí, un poco / un poco de náuseas nada más /
sí, estoy bien consciente / sí, hablo bien / tengo hipertensión
```

**Resultado:**
```
Síntoma principal:   dolor torácico
Inicio:              hace una hora
Tipo de dolor:       presión
Intensidad:          7
Localización:        centro del pecho
Irradiación:         brazo izquierdo
Síntomas asociados:  disnea leve, náuseas leves
Antecedentes:        hipertensión
Señales de alarma:   Ninguno

Clasificación preliminar: Clave 2
Justificación: Dolor retroesternal de inicio reciente con irradiación al brazo
izquierdo, intensidad moderada, disnea leve y antecedentes de hipertensión.
```

**Observación:** en una primera prueba con "sudo bastante" en lugar de "un poco de náuseas", el sistema clasificó como Clave 1. Ver sección de conclusiones.

---

### Escenario B — Corte por Clave 1

**Objetivo:** verificar que el sistema interrumpa el cuestionario de forma inmediata ante señales de alarma, sin importar en qué punto del protocolo se encuentre.

**Entradas utilizadas:**
```
me duele el pecho / hace 10 minutos / [ante cualquier pregunta] me estoy desmayando, no puedo respirar
```

**Resultado:** el sistema interrumpió el cuestionario en el tercer turno, ignorando la pregunta que iba a hacer, y emitió el mensaje de escalada:

> "Por la información que me dio, su situación puede requerir atención inmediata. Por favor llame al número de emergencias de AEM ahora."

**Reasoning interno registrado:** *"El paciente reporta dificultad respiratoria extrema y sensación de desmayo, lo cual son señales de Clave 1."*

---

### Escenario C — Respuestas evasivas

**Objetivo:** verificar que el sistema maneje respuestas no relacionadas sin quedar atrapado en un loop ni inventar valores para los campos no respondidos.

**Entradas utilizadas:**
```
me duele el pecho / hace una hora / es como una presión / 7 /
[ante pregunta de localización] no sé, ayer estaba bien y de repente me agarró esto /
[segunda vez] no tengo idea, simplemente me duele /
no / no / no / sí, estoy consciente / sí, hablo bien / no tengo antecedentes
```

**Resultado:**
```
Localización: No precisado por el socio

Clasificación preliminar: Clave 3
Justificación: Dolor de intensidad 7 sin irradiación ni síntomas neurovegetativos,
consciente y habla normal, sin antecedentes cardiovasculares.
```

**Reasoning interno registrado (turno evasivo 1):** *"Reformulo la pregunta para obtener la localización precisa del dolor, ya que la respuesta anterior fue evasiva (intento 1)."*

**Reasoning interno registrado (turno evasivo 2):** *"El socio no pudo precisar la localización del dolor tras dos intentos, por lo que se registra como 'No precisado por el socio'. Ahora se evalúa la irradiación del dolor."*

---

## Conclusiones

### 1. Los tres flujos principales funcionan correctamente

El sistema completa el cuestionario, detecta Clave 1 en tiempo real y maneja respuestas evasivas de acuerdo a lo especificado. El resumen generado es coherente con los datos recolectados y la justificación clínica es consistente con los criterios del protocolo.

### 2. El sesgo conservador hacia Clave 1 es consistente con el principio de diseño del sistema

Durante las pruebas el sistema clasificó como Clave 1 un perfil que combinaba dolor opresivo, irradiación al brazo izquierdo, disnea leve y "sudo bastante". Esto podría interpretarse como un falso positivo respecto a Clave 2, pero es el comportamiento esperable por dos razones que conviene distinguir:

- **El protocolo clínico de AEM trata los síntomas neurovegetativos como presencia/ausencia**, sin gradación entre leve, moderado e intenso. El modelo no tiene base documental para distinguir "sudo un poco" de "sudoración profusa", por lo que ante la ambigüedad interpreta el síntoma en su forma más grave.
- **El principio de diseño del sistema establece escalada ante la duda.** Este principio no está definido explícitamente en el protocolo clínico de AEM sino en los requisitos del sistema: ante síntomas ambiguos, el sistema debe derivar al médico coordinador antes de clasificar, no tomar la decisión solo. Un falso positivo de Clave 1 (movilizar recursos innecesariamente) es preferible a un falso negativo (no atender una emergencia real).

Son dos fuentes distintas: el protocolo clínico explica por qué el modelo no puede graduar el síntoma; el principio de diseño explica por qué escalar es la respuesta correcta ante esa limitación. Este comportamiento valida la **arquitectura híbrida** planteada en el proyecto: el sistema clasifica los casos claros de forma autónoma y escala los casos ambiguos para que un humano decida.

### 3. La clasificación zero-shot tiene limitaciones en casos borderline

En este prototipo el modelo clasifica sin haber visto ejemplos previos de clasificaciones reales de AEM. Eso introduce inconsistencias ante perfiles ambiguos porque el modelo interpreta los criterios con su conocimiento médico general, que puede no coincidir exactamente con el criterio operacional de AEM.

---

## Limitaciones del prototipo

- **Un solo cuadro clínico implementado:** solo dolor torácico. El sistema detecta el cuadro por palabras clave simples; si el socio no menciona "pecho" o "tórax", no carga ningún árbol.
- **Sin persistencia:** la conversación vive solo en memoria durante la sesión. No hay registro de sesiones anteriores ni integración con sistemas de AEM.
- **Interfaz de terminal:** sin interfaz de voz ni integración telefónica.
- **Clasificación zero-shot:** sin ejemplos de referencia calibrados con el criterio real de AEM, lo que genera ambigüedad en casos borderline.

---

## Próximos pasos

### Few-shot prompting para clasificación calibrada

El few-shot prompting se aplica exclusivamente en la clasificación final. Cuando el cuestionario termina y todos los campos están recolectados, se hace una llamada separada al modelo cuyo único propósito es clasificar el caso en Clave 1, 2 o 3. En esa llamada, además del perfil clínico del socio, se incluyen casos de ejemplo, cada uno mostrando un conjunto de síntomas con su clasificación correcta y su justificación. El modelo usa esos ejemplos como referencia para clasificar el caso nuevo por analogía, en lugar de razonar desde cero con su conocimiento médico general. El efecto concreto es que la clasificación queda calibrada con el criterio operacional de AEM en lugar de depender de cómo el modelo interpreta los síntomas en abstracto, lo que reduce la ambigüedad en casos borderline.

La cantidad de ejemplos varía por cuadro según su complejidad. Los cuadros con tres niveles de clasificación y casos borde documentados — dolor torácico, trauma, disnea, pérdida de conocimiento, convulsión, diabetes e intento de autoeliminación — requieren entre 15 y 20 ejemplos cada uno para cubrir las presentaciones típicas y los bordes. Los cuadros con dos niveles y criterios más acotados requieren entre 8 y 12 ejemplos. Los cuadros de un solo nivel alcanzan con 4 a 6 ejemplos bien elegidos. En total, para los 26 cuadros del protocolo, la estimación es de entre 250 y 350 ejemplos. Los cuadros que el protocolo define como exclusivamente Clave 3 no requieren llamada al clasificador: la clasificación se asigna directamente en el código.

Los casos de ejemplo se van a generar con IA generativa usando como base los documentos del protocolo clínico de AEM y los casos reales que el cliente compartió, que se usan como semilla para producir variaciones sintéticas que cubran los distintos cuadros clínicos y niveles de clasificación. Si se usan casos reales en cualquier forma, corresponde revisar el supuesto SUP-01 de la documentación del proyecto, que establece que el sistema opera con datos de prueba.

### Otras líneas de evolución

- Incorporar nuevos cuadros clínicos (disnea, síncope, dolor abdominal)
- Mejorar la detección del cuadro clínico reemplazando el keyword matching por una clasificación con el modelo
- Agregar gradación de síntomas neurovegetativos en el árbol para reducir falsos positivos de Clave 1
- Integración con interfaz de voz para replicar el canal telefónico real
