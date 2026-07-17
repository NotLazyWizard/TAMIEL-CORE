"""
utils/generador_txt.py — Genera archivos .txt de preview para correos.

Crea un archivo de texto legible con el contenido del correo
para que el usuario lo revise antes de enviar.
"""

import logging
from pathlib import Path

from config.settings import DATA_DIR

logger = logging.getLogger(__name__)

PREVIEW_DIR = DATA_DIR / "previews"


def generar_txt(correo_dict: dict, correo_id: int) -> Path:
    """Genera un archivo .txt con la vista previa del correo.
    
    Args:
        correo_dict: Diccionario con datos del correo (destinatarios, asunto, cuerpo, adjuntos).
        correo_id: ID del correo en la base de datos.
    
    Returns:
        Ruta al archivo .txt generado.
    """
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)

    ruta_txt = PREVIEW_DIR / f"correo_{correo_id}.txt"

    destinatarios = correo_dict.get("destinatarios", "No especificados")
    if isinstance(destinatarios, list):
        destinatarios = ", ".join(destinatarios)

    emails = correo_dict.get("destinatarios_email", "Sin resolver")
    if isinstance(emails, list):
        emails = ", ".join(emails)

    asunto = correo_dict.get("asunto", "Sin asunto")
    cuerpo = correo_dict.get("cuerpo", "Sin contenido")

    adjuntos = correo_dict.get("adjuntos", [])
    if isinstance(adjuntos, list):
        adjuntos_texto = ", ".join(adjuntos) if adjuntos else "Ninguno"
    else:
        adjuntos_texto = adjuntos or "Ninguno"

    contenido = (
        f"{'='*60}\n"
        f"  BORRADOR DE CORREO — ID {correo_id}\n"
        f"{'='*60}\n\n"
        f"Para:     {destinatarios}\n"
        f"Emails:   {emails}\n"
        f"Asunto:   {asunto}\n"
        f"Adjuntos: {adjuntos_texto}\n\n"
        f"{'-'*60}\n\n"
        f"{cuerpo}\n\n"
        f"{'-'*60}\n"
        f"Fin del borrador\n"
    )

    ruta_txt.write_text(contenido, encoding="utf-8")
    logger.info("Preview generado: %s", ruta_txt)

    return ruta_txt
