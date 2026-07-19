"""
ai/knowledge_extractor.py — Extractor de conocimiento documental.

Responsabilidad única:
    - Recibir texto plano
    - Utilizar un LLM para generar conocimiento estructurado
    - Retornar un resultado tipado

Nunca accede a la base de datos.
Nunca abre archivos.
"""

import json
import logging
from dataclasses import dataclass, field

from ai.llm_provider import LLMProvider
from config.settings import DOC_MAX_TOKENS_LLM

logger = logging.getLogger(__name__)


@dataclass
class KnowledgeResult:
    """Resultado de la extracción de conocimiento de un documento."""

    resumen: str
    tipo_documento: str
    json_completo: dict = field(default_factory=dict)
    modelo: str = ""
    version_prompt: str = ""


SYSTEM_PROMPT = """Eres un analista documental profesional.

Tu ÚNICA tarea es recibir el texto de un documento y devolver EXCLUSIVAMENTE un JSON válido con el análisis estructurado del contenido.

REGLAS ESTRICTAS:
1. SOLO responde con JSON. NUNCA texto libre, explicaciones ni comentarios.
2. Analiza el contenido de forma exhaustiva.
3. Extrae TODAS las entidades mencionadas (personas, empresas, lugares, etc.).
4. Identifica relaciones entre entidades cuando sea posible.
5. El resumen debe ser conciso pero informativo (máximo 3 párrafos).
6. Clasifica el tipo de documento con precisión.

FORMATO DE SALIDA (JSON estricto):
{
    "resumen": "Resumen conciso del contenido del documento",
    "tipo_documento": "informe|contrato|factura|carta|presentacion|hoja_calculo|manual|acta|propuesta|curriculum|otro",
    "personas": ["Nombre completo 1", "Nombre completo 2"],
    "empresas": ["Empresa 1"],
    "organizaciones": ["Organización 1"],
    "lugares": ["Ciudad, País"],
    "fechas": ["2024-01-15"],
    "temas": ["tema principal 1", "tema principal 2"],
    "palabras_clave": ["keyword1", "keyword2", "keyword3"],
    "entidades": [
        {"nombre": "Nombre", "tipo": "persona|empresa|organizacion|lugar|fecha|producto|otro"}
    ],
    "relaciones": [
        {"origen": "Persona X", "relacion": "trabaja_en|dirige|pertenece_a|menciona|contrata|otro", "destino": "Empresa Y"}
    ]
}

NOTAS:
- Si un campo no aplica, usa una lista vacía [].
- Las fechas deben estar en formato ISO (YYYY-MM-DD) cuando sea posible.
- Las relaciones solo deben incluirse cuando sean claras en el texto.
- Responde ÚNICAMENTE con el JSON. Sin ```json, sin markdown, sin explicaciones."""


class KnowledgeExtractor:
    """Extrae conocimiento estructurado de texto usando un LLM.

    No accede a archivos ni base de datos. Solo procesa texto
    que recibe como parámetro.

    Args:
        llm_provider: Proveedor de LLM a utilizar.
    """

    PROMPT_VERSION = "1.0"

    def __init__(self, llm_provider: LLMProvider):
        self.llm = llm_provider

    def extraer_conocimiento(
        self,
        texto: str,
        titulo: str = "",
    ) -> KnowledgeResult:
        """Envía texto al LLM y devuelve conocimiento estructurado.

        Args:
            texto: Texto completo del documento.
            titulo: Título del documento (opcional, añade contexto).

        Returns:
            KnowledgeResult con el análisis completo.
        """
        if not texto or not texto.strip():
            logger.warning("Texto vacío recibido para extracción de conocimiento.")
            return KnowledgeResult(
                resumen="Documento sin contenido textual extraíble.",
                tipo_documento="otro",
                json_completo={},
                modelo=getattr(self.llm, "model", "desconocido"),
                version_prompt=self.PROMPT_VERSION,
            )

        # Truncar texto para no exceder límite de tokens del LLM
        # Estimación conservadora: 1 token ≈ 4 caracteres
        max_chars = DOC_MAX_TOKENS_LLM * 4
        texto_truncado = texto[:max_chars]

        if len(texto) > max_chars:
            logger.info(
                "Texto truncado para LLM: %d → %d caracteres (límite: %d tokens).",
                len(texto), max_chars, DOC_MAX_TOKENS_LLM,
            )

        # Construir prompt del usuario
        partes = []
        if titulo:
            partes.append(f"TÍTULO DEL DOCUMENTO: {titulo}")
        partes.append(f"CONTENIDO DEL DOCUMENTO:\n\n{texto_truncado}")
        prompt_usuario = "\n\n".join(partes)

        logger.info(
            "Extrayendo conocimiento (título: '%s', %d chars, prompt v%s)...",
            titulo or "sin título", len(texto_truncado), self.PROMPT_VERSION,
        )

        try:
            resultado_json = self.llm.generate_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=prompt_usuario,
                temperature=0.2,
                max_tokens=4000,
            )

            resumen = resultado_json.get("resumen", "Sin resumen disponible.")
            tipo_doc = resultado_json.get("tipo_documento", "otro")

            logger.info(
                "Conocimiento extraído: tipo='%s', %d entidades, %d relaciones.",
                tipo_doc,
                len(resultado_json.get("entidades", [])),
                len(resultado_json.get("relaciones", [])),
            )

            return KnowledgeResult(
                resumen=resumen,
                tipo_documento=tipo_doc,
                json_completo=resultado_json,
                modelo=getattr(self.llm, "model", "desconocido"),
                version_prompt=self.PROMPT_VERSION,
            )

        except Exception as e:
            logger.error(
                "Error en extracción de conocimiento: %s", e, exc_info=True,
            )
            return KnowledgeResult(
                resumen=f"Error en extracción: {str(e)[:200]}",
                tipo_documento="otro",
                json_completo={"error": str(e)},
                modelo=getattr(self.llm, "model", "desconocido"),
                version_prompt=self.PROMPT_VERSION,
            )
