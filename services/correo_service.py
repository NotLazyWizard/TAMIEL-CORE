"""
services/correo_service.py — Lógica de negocio principal para correos.

Orquesta el flujo completo:
    Audio → Transcripción → Redacción → Resolución → Guardado → Aprobación → Envío

Cada función coordina múltiples servicios pero no implementa lógica
de transporte (Telegram, Gmail) directamente.
"""

import json
import logging
from pathlib import Path
from sqlalchemy.orm import Session

from ai.transcriptor import transcribir_audio
from ai.redactor import redactar_correo
from config.database import Correos, EstadoCorreo, get_db
from config.settings import MAX_REWRITE_ATTEMPTS
from services.estado_service import transicionar_estado
from services.resolucion_service import (
    resolver_destinatarios,
    resolver_documentos,
    ResultadoResolucion,
    formatear_problemas_resolucion,
)

logger = logging.getLogger(__name__)


# ─── Resultado del procesamiento ──────────────────────────────────

class ResultadoProcesamiento:
    """Resultado del procesamiento de una nota de voz."""

    def __init__(self, correo: Correos):
        self.correo: Correos = correo
        self.problemas_resolucion: str | None = None  # Mensaje con problemas
        self.res_destinatarios: ResultadoResolucion | None = None
        self.res_documentos: ResultadoResolucion | None = None

    @property
    def tiene_problemas(self) -> bool:
        return self.problemas_resolucion is not None


# ─── Procesar nota de voz ─────────────────────────────────────────

def procesar_nota_voz(
    ruta_audio: str | Path,
    message_id: int,
    db: Session,
) -> ResultadoProcesamiento:
    """Procesa una nota de voz: transcribe, redacta y resuelve entidades.
    
    Args:
        ruta_audio: Ruta al archivo de audio descargado.
        message_id: ID del mensaje de Telegram.
        db: Sesión de base de datos.
    
    Returns:
        ResultadoProcesamiento con el correo creado e info de resolución.
    """
    # 1. Crear registro en DB con estado NOTA_RECIBIDA
    correo = Correos(
        message_id=message_id,
        estado=EstadoCorreo.NOTA_RECIBIDA,
    )
    db.add(correo)
    db.commit()
    db.refresh(correo)

    logger.info("Correo ID %d creado (nota de voz recibida).", correo.id)

    # 2. Transcribir audio → texto
    transicionar_estado(correo, EstadoCorreo.REDACTANDO, db)
    texto_transcrito = transcribir_audio(ruta_audio)
    correo.texto_transcrito = texto_transcrito
    db.commit()

    # 3. Redactar correo → JSON
    correo_dict = redactar_correo(texto_transcrito)
    correo.intentos_redaccion = 1

    # 4. Guardar datos del JSON en el modelo
    _aplicar_json_a_correo(correo, correo_dict)
    db.commit()

    # 5. Resolver entidades (Python, no LLM)
    resultado = ResultadoProcesamiento(correo)
    _resolver_entidades(correo, correo_dict, db, resultado)

    # 6. Transicionar a ESPERANDO_APROBACION
    transicionar_estado(correo, EstadoCorreo.ESPERANDO_APROBACION, db)

    return resultado


# ─── Aplicar feedback ─────────────────────────────────────────────

def aplicar_feedback(
    correo_id: int,
    feedback_texto: str,
    db: Session,
) -> ResultadoProcesamiento | None:
    """Re-redacta un correo aplicando el feedback del usuario.
    
    Args:
        correo_id: ID del correo a modificar.
        feedback_texto: Texto de feedback del usuario.
        db: Sesión de base de datos.
    
    Returns:
        ResultadoProcesamiento actualizado, o None si el correo no existe
        o no está en estado ESPERANDO_APROBACION.
    """
    correo = db.query(Correos).filter(
        Correos.id == correo_id,
        Correos.estado == EstadoCorreo.ESPERANDO_APROBACION,
    ).first()

    if not correo:
        return None

    if correo.intentos_redaccion >= MAX_REWRITE_ATTEMPTS:
        logger.warning(
            "Correo ID %d: se alcanzó el límite de %d intentos de redacción.",
            correo_id, MAX_REWRITE_ATTEMPTS,
        )
        return None

    # Transicionar a REDACTANDO
    transicionar_estado(correo, EstadoCorreo.REDACTANDO, db)

    # Reconstruir borrador anterior
    borrador_anterior = {
        "destinatarios": (correo.destinatarios or "").split(", "),
        "asunto": correo.asunto or "",
        "cuerpo": correo.cuerpo or "",
        "adjuntos": [],  # Los adjuntos se manejan por ID, no por nombre aquí
    }

    # Guardar feedback
    correo.feedback_usuario = feedback_texto

    # Re-redactar
    correo_dict = redactar_correo(
        texto=correo.texto_transcrito or "",
        feedback=feedback_texto,
        borrador_anterior=borrador_anterior,
    )
    correo.intentos_redaccion += 1

    # Aplicar nuevo JSON
    _aplicar_json_a_correo(correo, correo_dict)
    db.commit()

    # Re-resolver entidades
    resultado = ResultadoProcesamiento(correo)
    _resolver_entidades(correo, correo_dict, db, resultado)

    # Volver a ESPERANDO_APROBACION
    transicionar_estado(correo, EstadoCorreo.ESPERANDO_APROBACION, db)

    return resultado


# ─── Obtener resumen para Telegram ────────────────────────────────

def generar_resumen_correo(correo: Correos) -> str:
    """Genera un resumen legible del correo para enviar por Telegram.
    
    Args:
        correo: Instancia del correo.
    
    Returns:
        Texto formateado en Markdown para Telegram.
    """
    resumen = (
        f"📧 *Borrador de correo ID {correo.id}*\n\n"
        f"*Para:* {correo.destinatarios or 'No especificados'}\n"
        f"*Emails:* {correo.destinatarios_email or 'Sin resolver'}\n"
        f"*Asunto:* {correo.asunto or 'Sin asunto'}\n\n"
        f"*Cuerpo:*\n{correo.cuerpo or 'Sin contenido'}\n\n"
        f"*Adjuntos:* {correo.documentos or 'Ninguno'}\n"
        f"*Intentos de redacción:* {correo.intentos_redaccion}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ `/enviar_{correo.id}` — Enviar correo\n"
        f"📝 `/feedback_{correo.id} tu mensaje` — Solicitar cambios\n"
        f"❌ `/cancelar_{correo.id}` — Cancelar correo"
    )
    return resumen


# ─── Helpers internos ─────────────────────────────────────────────

def _aplicar_json_a_correo(correo: Correos, correo_dict: dict) -> None:
    """Aplica los datos del JSON del LLM al modelo de Correos."""
    destinatarios = correo_dict.get("destinatarios", [])
    correo.destinatarios = ", ".join(destinatarios) if destinatarios else None
    correo.asunto = correo_dict.get("asunto")
    correo.cuerpo = correo_dict.get("cuerpo")


def _resolver_entidades(
    correo: Correos,
    correo_dict: dict,
    db: Session,
    resultado: ResultadoProcesamiento,
) -> None:
    """Resuelve destinatarios y documentos, y actualiza el correo."""
    # Resolver destinatarios
    nombres_dest = correo_dict.get("destinatarios", [])
    res_dest = resolver_destinatarios(nombres_dest, db)
    resultado.res_destinatarios = res_dest

    if res_dest.resueltos:
        correo.destinatarios_email = ", ".join(
            d["correo"] for d in res_dest.resueltos
        )
        # Actualizar nombres con los nombres correctos de la DB
        correo.destinatarios = ", ".join(
            d["nombre"] for d in res_dest.resueltos
        )

    # Resolver documentos
    nombres_docs = correo_dict.get("adjuntos", [])
    res_docs = resolver_documentos(nombres_docs, db)
    resultado.res_documentos = res_docs

    if res_docs.resueltos:
        correo.documentos = ", ".join(
            str(d["id"]) for d in res_docs.resueltos
        )

    db.commit()

    # Generar mensaje de problemas si los hay
    resultado.problemas_resolucion = formatear_problemas_resolucion(
        res_dest, res_docs
    )
