#!/usr/bin/env python3
"""
AEM Questionnaire POC
Microservicio de cuestionario clínico conversacional por terminal.
"""
import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI()  # Lee OPENAI_API_KEY del .env

# Palabras clave para detectar el cuadro clínico en la primera respuesta del socio
CUADRO_KEYWORDS: dict[str, list[str]] = {
    "dolor_toracico": [
        "pecho", "corazón", "torácico", "tórax", "precordial",
        "opresión", "oprime", "cardíaco", "me aprieta", "me presiona",
        "duele el pecho", "dolor en el pecho", "dolor de pecho",
        "puntada en el pecho", "quemación en el pecho",
    ]
}

SEP = "─" * 54


def load_text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def detect_cuadro(text: str) -> str | None:
    """Detecta el cuadro clínico a partir de la primera respuesta libre del socio."""
    text_lower = text.lower()
    for cuadro, keywords in CUADRO_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return cuadro
    return None


def build_system_message(tree: dict | None) -> str:
    """Combina el prompt base con el árbol de protocolo activo."""
    prompt = load_text("prompts/system_prompt.txt")
    if tree:
        prompt += (
            "\n\n## ÁRBOL DE PROTOCOLO ACTIVO\n"
            "```json\n"
            + json.dumps(tree, ensure_ascii=False, indent=2)
            + "\n```"
        )
    return prompt


def call_model(conversation: list[dict], tree: dict | None) -> dict:
    """Llama a GPT-4o y retorna el JSON parseado."""
    messages = [{"role": "system", "content": build_system_message(tree)}] + conversation
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    return json.loads(response.choices[0].message.content)


def print_summary(summary: dict) -> None:
    """Imprime el resumen clínico estructurado en terminal."""
    print(f"\n{SEP}")
    print("         --- RESUMEN CLÍNICO AEM ---")
    print(SEP)

    fields = [
        ("Síntoma principal", "sintoma_principal"),
        ("Inicio", "inicio"),
        ("Tipo de dolor", "tipo"),
        ("Intensidad", "intensidad"),
        ("Localización", "localizacion"),
        ("Irradiación", "irradiacion"),
        ("Síntomas asociados", "sintomas_asociados"),
        ("Antecedentes", "antecedentes"),
        ("Señales de alarma", "senales_alarma"),
    ]
    for label, key in fields:
        val = summary.get(key, "No referido")
        if isinstance(val, list):
            val = ", ".join(val) if val else "Ninguno"
        print(f"  {label:<28} {val}")

    clasificacion = summary.get("clasificacion_preliminar", "No determinada")
    justificacion = summary.get("justificacion_clasificacion", "")
    print(f"\n  {'Clasificación preliminar':<28} {clasificacion}")
    if justificacion:
        print(f"  {'Justificación':<28} {justificacion}")
    print(SEP)


def main() -> None:
    print(SEP)
    print("    AEM — Asistente de Emergencias Médicas")
    print(SEP)

    conversation: list[dict] = []
    tree: dict | None = None
    cuadro: str | None = None

    # Saludo inicial fijo — no generado por el modelo
    greeting = "Hola, soy el asistente de AEM. ¿Cuál es el motivo de su consulta?"
    print(f"\nAsistente: {greeting}")
    conversation.append({"role": "assistant", "content": greeting})

    while True:
        try:
            user_input = input("\nSocio: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSesión terminada.")
            sys.exit(0)

        if not user_input:
            continue

        conversation.append({"role": "user", "content": user_input})

        # Detectar cuadro clínico en el primer turno relevante
        if cuadro is None:
            cuadro = detect_cuadro(user_input)
            if cuadro:
                tree = load_json(f"trees/{cuadro}.json")

        # Llamada al modelo
        try:
            response = call_model(conversation, tree)
        except Exception as exc:
            print(f"\n[Error al contactar el modelo: {exc}]")
            continue

        next_question: str = response.get(
            "next_question", "¿Puede contarme más sobre su situación?"
        )
        clave1_flag: bool = response.get("clave1_flag", False)
        conversation_complete: bool = response.get("conversation_complete", False)

        # Log interno de razonamiento (opcional — comentar en producción)
        reasoning = response.get("reasoning", "")
        if reasoning:
            print(f"  [interno] {reasoning}", flush=True)

        print(f"\nAsistente: {next_question}")
        conversation.append({"role": "assistant", "content": next_question})

        # Clave 1 — escalada inmediata, fin del flujo
        if clave1_flag:
            break

        # Cuestionario completo — mostrar resumen
        if conversation_complete:
            summary = response.get("summary")
            if summary:
                print_summary(summary)
            break


if __name__ == "__main__":
    main()
