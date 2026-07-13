import sys


def _preguntar_si_no(pregunta: str) -> bool:
    """
    Muestra la pregunta con opciones numeradas y repregunta hasta recibir
    una opción válida. Retorna True si el socio elige "Sí", False si elige "No".
    """
    print(f"\nAsistente: {pregunta}")
    print("  1) Sí")
    print("  2) No")
    while True:
        try:
            respuesta = input("Socio (1 o 2): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSesión terminada.")
            sys.exit(0)

        if respuesta == "1":
            return True
        if respuesta == "2":
            return False

        print("  Opción no válida, por favor elija 1 o 2.")


def _hay_downstream_condicional(preguntas: list, desde: int) -> bool:
    """True si alguna pregunta posterior tiene condicion_activacion definida."""
    return any(
        p.get("condicion_activacion") is not None
        for p in preguntas[desde + 1:]
    )


def run_screening(tree: dict) -> tuple[str | None, dict, str | None]:
    """
    Ejecuta las preguntas determinísticas definidas en el tree.

    Retorna:
        ("Clave 1", contexto, instruccion) si alguna respuesta dispara señal crítica.
        (None, contexto, None) si el paciente pasa el screening.

    instruccion: texto de pre-arribo (ej: "iniciar RCP") cuando el árbol distingue
    la instrucción según la respuesta. None si no aplica.
    """
    preguntas = tree.get("preguntas_deterministas", [])
    contexto: dict = {}

    for i, pq in enumerate(preguntas):

        # -- Cambio 1: condicion_activacion ------------------------------------
        # Si la pregunta tiene una condición de activación, evaluarla antes de
        # mostrarla. Actualmente el único valor soportado es "solo_si_inconsciente".
        condicion = pq.get("condicion_activacion")
        if condicion == "solo_si_inconsciente":
            if contexto.get("estado_actual_consciencia") != "No":
                continue  # paciente consciente o estado desconocido — saltar

        pregunta = pq["pregunta"]
        dispara_si = pq["dispara_clave1_si"]
        campo = pq.get("campo")

        es_si = _preguntar_si_no(pregunta)

        if campo:
            contexto[campo] = "Sí" if es_si else "No"

        # -- Cambio 2: patrón "dispara en ambas respuestas" --------------------
        # Cuando el árbol define accion_si_respira y accion_si_no_respira, Clave 1
        # se activa independientemente de la respuesta, con instrucción diferenciada.
        accion_si = pq.get("accion_si_respira")
        accion_no = pq.get("accion_si_no_respira")
        if accion_si and accion_no:
            instruccion = accion_si if es_si else accion_no
            return "Clave 1", contexto, instruccion

        # -- Cambio 3: disparo estándar con diferimiento -----------------------
        # Si la condición de disparo se cumple pero hay una pregunta condicional
        # posterior que aún no se ejecutó, diferir: registrar el contexto y
        # continuar para que esa pregunta se ejecute antes de escalar.
        dispara = (dispara_si == "si" and es_si) or (dispara_si == "no" and not es_si)
        if dispara:
            if _hay_downstream_condicional(preguntas, i):
                continue  # diferir — la pregunta condicional decide la escalada
            return "Clave 1", contexto, None

    return None, contexto, None
