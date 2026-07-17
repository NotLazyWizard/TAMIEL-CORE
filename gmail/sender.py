"""
gmail/sender.py — Envío de correos mediante Gmail API.

Construye mensajes MIME completos con soporte para:
- Múltiples destinatarios
- Adjuntos de cualquier tipo soportado
- Texto plano como cuerpo

El LLM nunca interactúa directamente con Gmail.
"""

import base64
import logging
import mimetypes
import os
from email.mime.application import MIMEApplication
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from googleapiclient.discovery import build

from config.settings import GMAIL_REMITENTE
from gmail.auth import obtener_credenciales

logger = logging.getLogger(__name__)


def enviar_correo_gmail(
    destinatarios: str,
    asunto: str,
    cuerpo: str,
    adjuntos: list[str] | None = None,
) -> bool:
    """Envía un correo usando Gmail API con OAuth2.
    
    Args:
        destinatarios: Correos electrónicos separados por coma.
        asunto: Asunto del correo.
        cuerpo: Cuerpo del correo (texto plano).
        adjuntos: Lista de rutas a archivos adjuntos.
    
    Returns:
        True si el correo se envió correctamente, False en caso de error.
    """
    try:
        creds = obtener_credenciales()
        service = build("gmail", "v1", credentials=creds)

        # Construir mensaje MIME
        mensaje = _construir_mensaje(
            remitente=GMAIL_REMITENTE,
            destinatarios=destinatarios,
            asunto=asunto,
            cuerpo=cuerpo,
            adjuntos=adjuntos or [],
        )

        # Codificar en base64 para Gmail API
        raw = base64.urlsafe_b64encode(
            mensaje.as_bytes()
        ).decode("utf-8")

        # Enviar
        resultado = service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()

        message_id = resultado.get("id", "desconocido")
        logger.info(
            "Correo enviado exitosamente. Gmail ID: %s, Para: %s",
            message_id, destinatarios,
        )
        return True

    except Exception as e:
        logger.error("Error al enviar correo: %s", e, exc_info=True)
        return False


def _construir_mensaje(
    remitente: str,
    destinatarios: str,
    asunto: str,
    cuerpo: str,
    adjuntos: list[str],
) -> MIMEMultipart:
    """Construye un mensaje MIME completo con cuerpo y adjuntos.
    
    Args:
        remitente: Correo del remitente.
        destinatarios: Correos destinatarios separados por coma.
        asunto: Asunto del correo.
        cuerpo: Cuerpo del correo.
        adjuntos: Rutas a archivos adjuntos.
    
    Returns:
        Mensaje MIME listo para enviar.
    """
    msg = MIMEMultipart()
    msg["From"] = remitente
    msg["To"] = destinatarios
    msg["Subject"] = asunto

    # Cuerpo del correo
    msg.attach(MIMEText(cuerpo, "plain", "utf-8"))

    # Adjuntar archivos
    for ruta_archivo in adjuntos:
        adjunto = _crear_adjunto(ruta_archivo)
        if adjunto:
            msg.attach(adjunto)

    return msg


def _crear_adjunto(ruta_archivo: str) -> MIMEBase | None:
    """Crea un adjunto MIME a partir de una ruta de archivo.
    
    Detecta automáticamente el tipo MIME del archivo.
    
    Args:
        ruta_archivo: Ruta al archivo a adjuntar.
    
    Returns:
        Adjunto MIME o None si no se puede leer el archivo.
    """
    ruta = Path(ruta_archivo)

    if not ruta.exists():
        logger.warning("Archivo adjunto no encontrado: %s", ruta)
        return None

    try:
        # Detectar tipo MIME
        mime_type, _ = mimetypes.guess_type(str(ruta))
        if mime_type is None:
            mime_type = "application/octet-stream"

        main_type, sub_type = mime_type.split("/", 1)

        with open(ruta, "rb") as f:
            contenido = f.read()

        adjunto = MIMEApplication(contenido, _subtype=sub_type)
        adjunto.add_header(
            "Content-Disposition",
            "attachment",
            filename=ruta.name,
        )

        logger.debug("Adjunto creado: %s (%s)", ruta.name, mime_type)
        return adjunto

    except Exception as e:
        logger.error("Error al crear adjunto %s: %s", ruta, e)
        return None
