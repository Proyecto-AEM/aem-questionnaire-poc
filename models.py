from typing import Any, Optional
from pydantic import BaseModel


class TurnResponse(BaseModel):
    next_question: str
    clave1_flag: bool
    conversation_complete: bool
    campos_recolectados: dict[str, Any]
    reasoning: str


class IdentificationResponse(BaseModel):
    cuadro_identificado: Optional[str] = None
    confianza: str
    opciones: list[str] = []
    mensaje: str = ""


class ClassificationResponse(BaseModel):
    clasificacion: str
    justificacion: str
