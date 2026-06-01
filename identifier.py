import json
from pathlib import Path

from openai import OpenAI

from models import IdentificationResponse


def identify_cuadro(client: OpenAI, descripcion: str) -> IdentificationResponse:
    cuadros_lines = []
    for tree_path in sorted(Path("trees").glob("*.json")):
        tree = json.loads(tree_path.read_text(encoding="utf-8"))
        cuadros_lines.append(f"- {tree['cuadro']}: {tree['descripcion']}")

    prompt_template = Path("prompts/identify_cuadro_prompt.txt").read_text(encoding="utf-8")
    system_prompt = prompt_template.replace(
        "{{cuadros_disponibles}}", "\n".join(cuadros_lines)
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": descripcion},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )
    raw = json.loads(response.choices[0].message.content)
    return IdentificationResponse(**raw)
