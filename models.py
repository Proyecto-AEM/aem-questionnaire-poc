from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel


class TurnResponse(BaseModel):
    next_question: str
    clave1_flag: bool
    tercero_detectado: bool
    conversation_complete: bool
    campos_recolectados: dict[str, Any]
    reasoning: str


class QuestionnaireOutcome(Enum):
    OK = "ok"
    CLAVE1 = "clave1"
    TERCERO_NO_TITULAR = "tercero_no_titular"


class IdentificationResponse(BaseModel):
    cuadro_identificado: Optional[str] = None
    confianza: str
    opciones: list[str] = []
    mensaje: str = ""
    tercero_detectado: bool = False


class ClassificationResponse(BaseModel):
    clasificacion: str
    justificacion: str
