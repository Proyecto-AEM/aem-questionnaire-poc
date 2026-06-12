# Previous Prototypes — AEM Questionnaire POC

---

## Prototype 1

Single clinical case (`dolor_toracico`) with a minimal architecture:

- Keyword matching to detect the case from the patient's first response
- Single model call per turn handling both the questionnaire and final classification
- Zero-shot classification included in the same call as the questionnaire
- No output validation

---

## Prototype 2

### Stack
- Python 3.11, OpenAI SDK 2.3, Pydantic 2.12
- Model: `gpt-4o-mini`
- No frameworks, no database, terminal interface

### Clinical cases implemented
| Case | File | Questions | Screening | Classification |
|---|---|---|---|---|
| Chest pain | `trees/dolor_toracico.json` | 13 | 2 questions | Few-shot |
| Fever | `trees/fiebre.json` | 8 | 2 questions | Fixed Clave 3 in code |
| Loss of consciousness | `trees/perdida_de_conocimiento.json` | 8 | 1 question | Few-shot |

### Execution flow

```
Initial greeting
  → patient describes reason for consultation
  → [CALL 1] identify_cuadro() — identifies case against trees/ catalog
      if low confidence → shows options, asks patient to choose
  → loads tree JSON for identified case
  → run_screening() — yes/no questions in pure code, no model
      if critical signal → immediate Clave 1, end
  → conversational loop turn by turn
      [CALL 2..N] call_model_validated() — one call per turn
          strict Pydantic validation, up to 3 retries per malformed response
          model detects Clave 1 on each response even if not the corresponding question
          if clave1_flag → immediate escalation, end
  → questionnaire complete
      if case == fever → Clave 3 directly in code
      else → [FINAL CALL] classify_cuadro() — few-shot with 15–20 examples
  → print clinical profile + classification
```

### Deterministic questions per case

| Case | Question | Triggers Clave 1 if |
|---|---|---|
| `dolor_toracico` | Is the patient conscious and able to respond? | answers NO |
| `dolor_toracico` | Can they breathe normally? | answers NO |
| `fiebre` | Are they having convulsions or are they unconscious? | answers YES |
| `fiebre` | Do they have difficulty breathing? | answers YES |
| `perdida_de_conocimiento` | Are they breathing right now? | answers NO |

### Pydantic schemas

```python
TurnResponse           # next_question, clave1_flag, conversation_complete, campos_recolectados, reasoning
IdentificationResponse # cuadro_identificado, confianza, opciones, mensaje
ClassificationResponse # clasificacion, justificacion
```

### File structure

```
main.py                  — full flow orchestration
models.py                — Pydantic schemas
identifier.py            — identify_cuadro(): independent model call
classifier.py            — classify_cuadro(): few-shot call; fever returns Clave 3 in code
deterministic.py         — run_screening(): yes/no questions without model

trees/
  dolor_toracico.json
  fiebre.json
  perdida_de_conocimiento.json

prompts/
  system_prompt.txt
  identify_cuadro_prompt.txt
  classify_cuadro_prompt.txt

data/
  examples_dolor_toracico.json          — 15 synthetic examples Clave 1/2/3
  examples_perdida_de_conocimiento.json — 16 synthetic examples Clave 1/2/3
```

### Changes applied during prototype 2 testing sessions

**1. Identification — medium confidence no longer advances directly**
`main.py / phase_identify()`: previously both `"alta"` and `"media"` advanced silently. Now only `"alta"` advances. With `"media"` the model returns a confirmation message shown to the patient, and the loop continues until reaching `"alta"`.

**2. System prompt — universal Clave 1 signals corrected**
`prompts/system_prompt.txt`: removed `"Patient unconscious or unresponsive"` as a universal signal. Replaced with more precise criteria:
- "Not breathing, apnea or agonal breathing" (condition 1)
- "Not breathing AND unresponsive — cardiorespiratory arrest" (condition 2)
- "Patient is fainting NOW during the call" (condition 5 — limited to ongoing episode, not prior)
- Explicit note: `"unresponsive" with confirmed breathing is NOT a universal Clave 1 criterion`

**3. Bug — escalation message was not being shown**
`main.py / phase_questionnaire()`: the model could set `clave1_flag = true` but put a normal question in `next_question`. The code was printing `next_question` before checking the flag, so the escalation message never appeared. Fix: check the flag before printing, and if active print `ESCALADA_MSG` directly from code without depending on the model.

**4. PDC tree — explicit note on stimulus response question**
`trees/perdida_de_conocimiento.json`: added note in `notas_clinicas` for the `respuesta_estimulos` question: "a patient being unresponsive with confirmed breathing is NOT a Clave 1 criterion in this case — it is the expected presentation of LOC."

**5. Chest pain tree — field name alignment**
`trees/dolor_toracico.json`: `estado_consciencia` → `consciencia` and `capacidad_habla` → `habla` in `secuencia_preguntas`, to match the `campos_schema` field names.

### Known limitations

- **Model activates Clave 1 on its own criteria for LOC:** given combinations like "unresponsive + diabetes" or "unresponsive + no recovery", the model escalates to Clave 1 even though the AEM manual classifies it as Clave 2. The correct criterion is: in LOC, if breathing → maximum Clave 2. The fix requires prompt engineering work belonging to prototype 3.
- **Neurovegetative signals without gradation:** "pallor" mentioned by the patient can trigger Clave 1 even if mild. The universal criteria ("extreme pallor", "profuse sweating") lack sufficient gradation for the model to apply them precisely.
- **LOC few-shot examples missing physical exertion context:** `data/examples_perdida_de_conocimiento.json` has no examples with physical exertion context classified as Clave 2, causing the classifier to tend toward Clave 3 in those profiles without risk factors.
