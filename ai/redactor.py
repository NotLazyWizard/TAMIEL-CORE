"""
ai/redactor.py — Agente Redactor.

Responsabilidad única: Texto → JSON estructurado del correo.
Soporta iteraciones con feedback del usuario.
"""

import json
import logging
import re

from ai.groq_client import obtener_cliente
from config.settings import GROQ_MODEL_REDACTOR

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres un asistente profesional de redacción de correos electrónicos empresariales.

Tu ÚNICA tarea es recibir una instrucción en lenguaje natural y devolver EXCLUSIVAMENTE un JSON válido con la estructura del correo.

REGLAS ESTRICTAS:
1. SOLO responde con JSON. NUNCA texto libre, explicaciones, ni comentarios.
2. NO inventes correos electrónicos. Usa SOLO los nombres de personas tal como se mencionan.
3. NO inventes rutas de archivos. Si se menciona un documento, usa su nombre lógico tal cual.
4. El cuerpo del correo debe ser profesional, claro y en español.
5. Si no se especifica un asunto, genera uno apropiado basado en el contenido.

FORMATO DE SALIDA (JSON estricto):
{
    "destinatarios": ["Nombre1", "Nombre2"],
    "asunto": "Asunto del correo",
    "cuerpo": "Cuerpo completo del correo con saludo y despedida",
    "adjuntos": ["Nombre del documento 1"]
}

NOTAS:
- "destinatarios" es una lista de NOMBRES (nunca correos electrónicos).
- "adjuntos" es una lista de NOMBRES LÓGICOS de documentos. Si no hay adjuntos, usa una lista vacía [].
- "cuerpo" debe incluir saludo, contenido y despedida profesional.
- Responde ÚNICAMENTE con el JSON. Sin ```json, sin markdown, sin explicaciones."""


def redactar_correo(
    texto: str,
    feedback: str | None = None,
    borrador_anterior: dict | None = None,
) -> dict:
    """Redacta un correo electrónico a partir de texto con el LLM.
    
    Args:
        texto: Texto transcrito de la nota de voz.
        feedback: Feedback opcional del usuario para iterar.
        borrador_anterior: JSON del borrador anterior para refinamiento.
    
    Returns:
        Diccionario con las claves: destinatarios, asunto, cuerpo, adjuntos.
    
    Raises:
        ValueError: Si el LLM no devuelve un JSON válido.
    """
    mensajes = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Construir el prompt del usuario
    if borrador_anterior and feedback:
        # Iteración con feedback
        prompt_usuario = (
            f"INSTRUCCIÓN ORIGINAL:\n{texto}\n\n"
            f"BORRADOR ANTERIOR:\n{json.dumps(borrador_anterior, ensure_ascii=False, indent=2)}\n\n"
            f"FEEDBACK DEL USUARIO:\n{feedback}\n\n"
            "Por favor, genera una versión corregida del correo aplicando el feedback. "
            "Responde SOLO con el JSON actualizado."
        )
    else:
        # Primera redacción
        prompt_usuario = f"Redacta un correo basado en esta instrucción:\n\n{texto}"

    mensajes.append({"role": "user", "content": prompt_usuario})

    logger.info("Enviando al redactor (modelo: %s)...", GROQ_MODEL_REDACTOR)

    cliente = obtener_cliente()

    respuesta = cliente.chat.completions.create(
        model=GROQ_MODEL_REDACTOR,
        messages=mensajes,
        temperature=0.3,
        max_tokens=2000,
    )

    contenido = respuesta.choices[0].message.content.strip()
    logger.debug("Respuesta del redactor: %s", contenido[:200])

    # Limpiar posible markdown del LLM
    correo_dict = _parsear_json_respuesta(contenido)

    # Validar estructura
    _validar_estructura(correo_dict)

    logger.info("Correo redactado correctamente.")
    return correo_dict


def _parsear_json_respuesta(contenido: str) -> dict:
    """Extrae y parsea JSON de la respuesta del LLM, limpiando markdown si es necesario.
    
    Args:
        contenido: Texto de respuesta del LLM.
    
    Returns:
        Diccionario parseado del JSON.
    
    Raises:
        ValueError: Si no se puede extraer JSON válido.
    """
    # Intentar parseo directo
    try:
        return json.loads(contenido)
    except json.JSONDecodeError:
        pass

    # Intentar extraer JSON de bloques de código markdown
    patron_json = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", contenido, re.DOTALL)
    if patron_json:
        try:
            return json.loads(patron_json.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Intentar encontrar el primer { ... } válido
    patron_llaves = re.search(r"\{.*\}", contenido, re.DOTALL)
    if patron_llaves:
        try:
            return json.loads(patron_llaves.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"El redactor no devolvió un JSON válido. Respuesta: {contenido[:300]}"
    )


def _validar_estructura(correo_dict: dict) -> None:
    """Valida que el JSON del correo tenga la estructura esperada.
    
    Args:
        correo_dict: Diccionario a validar.
    
    Raises:
        ValueError: Si faltan campos obligatorios o tienen tipos incorrectos.
    """
    campos_requeridos = {"destinatarios", "asunto", "cuerpo"}
    faltantes = campos_requeridos - set(correo_dict.keys())

    if faltantes:
        raise ValueError(f"Campos faltantes en el JSON del correo: {faltantes}")

    if not isinstance(correo_dict["destinatarios"], list):
        raise ValueError("'destinatarios' debe ser una lista.")

    if not isinstance(correo_dict["asunto"], str):
        raise ValueError("'asunto' debe ser un string.")

    if not isinstance(correo_dict["cuerpo"], str):
        raise ValueError("'cuerpo' debe ser un string.")

    # Asegurar que adjuntos sea una lista (puede estar ausente)
    if "adjuntos" not in correo_dict:
        correo_dict["adjuntos"] = []
    elif not isinstance(correo_dict["adjuntos"], list):
        raise ValueError("'adjuntos' debe ser una lista.")
