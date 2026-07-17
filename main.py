#!/usr/bin/env python3
"""
AEM Questionnaire POC — Prototipo 2
Microservicio de cuestionario clínico conversacional por terminal.
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from classifier import classify_cuadro
from identifier import identify_cuadro
from models import ClassificationResponse, QuestionnaireOutcome, TurnResponse

load_dotenv()
client = OpenAI()

_AFIRMATIVO = {"si", "sí", "s", "yes", "y", "1", "afirmativo", "correcto"}


def es_si(respuesta: str) -> bool:
    return respuesta.strip().lower() in _AFIRMATIVO

SEP = "─" * 54
ESCALADA_MSG = (
    "Por la información que me dio, su situación puede requerir "
    "atención inmediata. Por favor llame al número de emergencias de AEM ahora."
)
CIERRE_MSG = (
    "Gracias por la información. Estamos procesando los datos "
    "y en un momento le indicamos cómo proceder."
)
CONFIRMAR_TITULAR_MSG = "¿Está consultando por el titular de esta cuenta?"
CORTE_TERCERO_MSG = (
    "Este canal está habilitado exclusivamente para que el titular de la "
    "cuenta consulte por sí mismo. Si necesita atención para otra persona, "
    "esa persona debe ingresar con su propia cuenta, o puede comunicarse "
    "telefónicamente con AEM."
)
FALLA_TECNICA_MSG = (
    "Tuvimos un problema técnico y no podemos continuar con el cuestionario. "
    "Por favor comuníquese con AEM para recibir atención."
)


def load_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_system_message(tree: dict) -> str:
    prompt = load_text("prompts/system_prompt.txt")
    campos_schema_json = json.dumps(
        tree.get("campos_schema", {}), ensure_ascii=False, indent=2
    )
    prompt = prompt.replace("{{campos_schema}}", campos_schema_json)
    prompt += (
        "\n\n## ÁRBOL DE PROTOCOLO ACTIVO\n"
        "```json\n"
        + json.dumps(tree, ensure_ascii=False, indent=2)
        + "\n```"
    )
    return prompt


def call_model_validated(
    conversation: list[dict], tree: dict, max_retries: int = 3
) -> TurnResponse:
    messages = [{"role": "system", "content": build_system_message(tree)}] + conversation
    last_error: Exception | None = None

    for _ in range(max_retries):
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        contenido = response.choices[0].message.content
        try:
            raw = json.loads(contenido)
            return TurnResponse(**raw)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            messages.append({"role": "assistant", "content": contenido})
            messages.append({
                "role": "user",
                "content": (
                    f"Tu respuesta anterior no es un JSON válido según el formato "
                    f"esperado: {exc}. Corregí y respondé de nuevo únicamente con "
                    f"el JSON en el formato indicado."
                ),
            })

    raise RuntimeError(
        f"La respuesta del modelo fue inválida luego de {max_retries} intentos: {last_error}"
    )


def confirm_titular() -> bool:
    """Pregunta al socio si consulta por el titular de la cuenta. Retorna True si confirma."""
    print(f"\nAsistente: {CONFIRMAR_TITULAR_MSG}")
    try:
        confirmacion = input("\nSocio: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n\nSesión terminada.")
        sys.exit(0)
    return es_si(confirmacion)


def print_results(campos: dict, clasificacion_result: ClassificationResponse) -> None:
    print(f"\n{SEP}")
    print("      --- PERFIL CLÍNICO (campos_recolectados) ---")
    print(SEP)
    for key, val in campos.items():
        display = ", ".join(val) if isinstance(val, list) else str(val)
        print(f"  {key:<32} {display}")
    print(SEP)
    print(f"\n  {'Clasificación':<28} {clasificacion_result.clasificacion}")
    print(f"  {'Justificación':<28} {clasificacion_result.justificacion}")
    print(SEP)


def phase_identify() -> tuple[str, str, dict, bool] | None:
    """
    Identificación del cuadro clínico — llamada independiente al modelo.
    Retorna (descripcion_inicial, cuadro, tree, titular_confirmado),
    o None si se corta por tercero no confirmado como titular.
    """
    print(f"\n{SEP}")
    print("    AEM — Asistente de Emergencias Médicas")
    print(SEP)

    greeting = "Hola, soy el asistente de AEM. ¿Cuál es el motivo de su consulta?"
    print(f"\nAsistente: {greeting}")

    try:
        user_input = input("\nSocio: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n\nSesión terminada.")
        sys.exit(0)

    if not user_input:
        user_input = "No especificado"

    descripcion_inicial = user_input
    identification_context = user_input

    titular_confirmado = False
    tercero_detectado_id = False

    while True:
        try:
            identification = identify_cuadro(client, identification_context)
        except Exception as exc:
            print(f"\nAsistente: {FALLA_TECNICA_MSG}")
            sys.exit(1)

        if identification.tercero_detectado and not tercero_detectado_id:
            tercero_detectado_id = True
            if not confirm_titular():
                print(f"\nAsistente: {CORTE_TERCERO_MSG}")
                return None
            titular_confirmado = True

        if identification.cuadro_identificado and identification.confianza == "alta":
            cuadro = identification.cuadro_identificado
            tree_path = Path(f"trees/{cuadro}.json")
            if tree_path.exists():
                return descripcion_inicial, cuadro, load_json(str(tree_path)), titular_confirmado

        # Confianza media o baja — mostrar mensaje y pedir confirmación o más info
        mensaje = identification.mensaje or "¿Puede contarme con más detalle cuál es el síntoma principal?"
        print(f"\nAsistente: {mensaje}")

        try:
            more_info = input("\nSocio: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSesión terminada.")
            sys.exit(0)

        identification_context += f"\n{more_info}"


def phase_questionnaire(
    descripcion_inicial: str,
    tree: dict,
    titular_confirmado: bool = False,
) -> tuple[dict, QuestionnaireOutcome]:
    """
    Loop conversacional turno a turno con validación Pydantic y reintentos.
    Retorna (campos_acumulados, outcome).
    """
    conversation: list[dict] = [{"role": "user", "content": descripcion_inicial}]

    campos_acumulados: dict = {}

    while True:
        try:
            response = call_model_validated(conversation, tree)
        except Exception as exc:
            print(f"\nAsistente: {FALLA_TECNICA_MSG}")
            sys.exit(1)

        campos_acumulados.update(response.campos_recolectados)

        if response.reasoning:
            print(f"  [interno] {response.reasoning}", flush=True)

        if response.clave1_flag:
            print(f"\nAsistente: {ESCALADA_MSG}")
            return campos_acumulados, QuestionnaireOutcome.CLAVE1

        if response.tercero_detectado and not titular_confirmado:
            if confirm_titular():
                titular_confirmado = True
            else:
                print(f"\nAsistente: {CORTE_TERCERO_MSG}")
                return campos_acumulados, QuestionnaireOutcome.TERCERO_NO_TITULAR

        if response.conversation_complete:
            print(f"\nAsistente: {CIERRE_MSG}")
            return campos_acumulados, QuestionnaireOutcome.OK

        print(f"\nAsistente: {response.next_question}")
        conversation.append({"role": "assistant", "content": response.next_question})

        try:
            user_input = input("\nSocio: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSesión terminada.")
            sys.exit(0)

        if not user_input:
            continue

        conversation.append({"role": "user", "content": user_input})


def main() -> None:
    # 1. Identificación del cuadro — llamada independiente al modelo
    identify_result = phase_identify()
    if identify_result is None:
        return
    descripcion_inicial, cuadro, tree, titular_confirmado = identify_result

    # 2. Cuestionario conversacional — loop turno a turno con validación Pydantic
    campos, outcome = phase_questionnaire(descripcion_inicial, tree, titular_confirmado)

    if outcome != QuestionnaireOutcome.OK:
        return

    # 3. Clasificación final — llamada independiente con few-shot
    if tree.get("clasificacion_fija") == "Clave 3":
        clasificacion_result = ClassificationResponse(
            clasificacion="Clave 3",
            justificacion="Clasificación Clave 3 asignada directamente por protocolo del cuadro.",
        )
    else:
        try:
            clasificacion_result = classify_cuadro(client, cuadro, tree, campos)
        except Exception as exc:
            print(f"\nAsistente: {FALLA_TECNICA_MSG}")
            return

    # 4. Mostrar resumen y clasificación
    print_results(campos, clasificacion_result)


if __name__ == "__main__":
    main()
