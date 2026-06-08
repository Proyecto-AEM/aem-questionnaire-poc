import json
from pathlib import Path

from openai import OpenAI

from models import ClassificationResponse


def classify_cuadro(
    client: OpenAI, cuadro: str, tree: dict, campos: dict
) -> ClassificationResponse:
    if cuadro == "fiebre":
        return ClassificationResponse(
            clasificacion="Clave 3",
            justificacion="Fiebre sin señales de alarma: clasificación Clave 3 asignada directamente por protocolo.",
        )

    examples_path = Path(f"data/examples_{cuadro}.json")
    examples = json.loads(examples_path.read_text(encoding="utf-8"))

    prompt_template = Path("prompts/classify_cuadro_prompt.txt").read_text(encoding="utf-8")

    criterios_text = json.dumps(
        tree.get("criterios_clasificacion", {}), ensure_ascii=False, indent=2
    )
    ejemplos_text = json.dumps(examples, ensure_ascii=False, indent=2)
    perfil_text = json.dumps(campos, ensure_ascii=False, indent=2)

    system_prompt = (
        prompt_template
        .replace("{{criterios_clasificacion}}", criterios_text)
        .replace("{{ejemplos}}", ejemplos_text)
        .replace("{{perfil_clinico}}", perfil_text)
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Clasificar el perfil clínico presentado."},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = json.loads(response.choices[0].message.content)
    return ClassificationResponse(**raw)
