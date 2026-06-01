import sys

_AFIRMATIVO = {"si", "sí", "s", "yes", "y", "1", "afirmativo", "correcto"}

def _es_si(respuesta: str) -> bool:
    return respuesta.strip().lower() in _AFIRMATIVO

def run_screening(tree: dict) -> tuple[str | None, dict]:
    """
    Hace las preguntas determinísticas definidas en el tree.

    Retorna:
        ("Clave 1", contexto) si alguna respuesta dispara señal crítica.
        (None, contexto) si el paciente pasa el screening.

    contexto: dict con los campos recogidos durante el screening,
    para inyectar como primer contexto al cuestionario conversacional.
    """
    preguntas = tree.get("preguntas_deterministas", [])
    contexto: dict = {}

    for pq in preguntas:
        pregunta = pq["pregunta"]
        dispara_si = pq["dispara_clave1_si"]
        campo = pq.get("campo")

        print(f"\nAsistente: {pregunta} (responda sí o no)")
        try:
            respuesta = input("Socio: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSesión terminada.")
            sys.exit(0)

        es_si = _es_si(respuesta)

        if campo:
            contexto[campo] = "Sí" if es_si else "No"

        if dispara_si == "si" and es_si:
            return "Clave 1", contexto
        if dispara_si == "no" and not es_si:
            return "Clave 1", contexto

    return None, contexto
