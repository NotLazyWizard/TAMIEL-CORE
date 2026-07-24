"""
telegram/handlers_correo.py — Handlers del flujo principal de correos.

Maneja: notas de voz, feedback, envío, cancelación y vista de correos.
"""

import logging
import os
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from config.database import (
    SessionLocal, Correos, Documentos, EstadoCorreo,
)
from services import document_repository as doc_repo
from config.settings import TELEGRAM_ADMIN_CHAT_ID, MAX_REWRITE_ATTEMPTS
from services.correo_service import (
    procesar_nota_voz,
    aplicar_feedback,
    generar_resumen_correo,
)
from services.estado_service import transicionar_estado
from utils.helpers import escapar_markdown, extraer_id, extraer_id_y_texto

logger = logging.getLogger(__name__)


def _es_admin(update: Update) -> bool:
    return update.effective_chat.id == TELEGRAM_ADMIN_CHAT_ID


def _obtener_adjuntos_correo(correo: Correos, db) -> list[Documentos]:
    """Obtiene los documentos adjuntos de un correo.

    Primero consulta la tabla puente CorreoDocumentos.
    Si no hay resultados (datos pre-migración), usa el fallback
    del campo string correo.documentos con split(',').

    Args:
        correo: Instancia del correo.
        db: Sesión de base de datos.

    Returns:
        Lista de documentos adjuntos.
    """
    # Intento 1: tabla relacional
    documentos = doc_repo.obtener_documentos_correo(db, correo.id)
    if documentos:
        return documentos

    # Fallback: campo string legacy
    if correo.documentos:
        resultado = []
        for doc_id_str in correo.documentos.split(","):
            doc_id_str = doc_id_str.strip()
            if doc_id_str.isdigit():
                doc = db.get(Documentos, int(doc_id_str))
                if doc:
                    resultado.append(doc)
        return resultado

    return []


# ─── Handler principal: Nota de voz ──────────────────────────────

async def manejar_nota_voz(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Procesa una nota de voz: transcribe, redacta y presenta borrador."""
    if not _es_admin(update):
        return

    voice = update.message.voice
    if not voice:
        return

    await update.message.reply_text("🎙️ Nota de voz recibida. Procesando...")

    db = SessionLocal()
    ruta_audio = None

    try:
        # Descargar audio a archivo temporal
        archivo_tg = await voice.get_file()
        ruta_audio = os.path.join(
            tempfile.gettempdir(),
            f"audio_{update.message.message_id}.ogg",
        )
        await archivo_tg.download_to_drive(custom_path=ruta_audio)

        # Procesar: transcripción → redacción → resolución
        resultado = procesar_nota_voz(
            ruta_audio=ruta_audio,
            message_id=update.message.message_id,
            db=db,
        )

        correo = resultado.correo

        # Mostrar transcripción
        await update.message.reply_text(
            f"📝 *Transcripción:*\n\n_{escapar_markdown(correo.texto_transcrito or '')}_",
            parse_mode="Markdown",
        )

        # Mostrar problemas de resolución si los hay
        if resultado.tiene_problemas:
            await update.message.reply_text(
                f"⚠️ *Problemas de resolución:*\n\n{resultado.problemas_resolucion}",
                parse_mode="Markdown",
            )

        # Mostrar resumen del borrador
        resumen = generar_resumen_correo(correo)
        await update.message.reply_text(resumen, parse_mode="Markdown")

    except Exception as e:
        logger.error("Error procesando nota de voz: %s", e, exc_info=True)
        await update.message.reply_text(
            f"❌ Error al procesar la nota de voz:\n`{str(e)[:300]}`",
            parse_mode="Markdown",
        )
    finally:
        db.close()
        # Limpiar audio temporal
        if ruta_audio and os.path.exists(ruta_audio):
            os.remove(ruta_audio)


# ─── Cancelar correo ──────────────────────────────────────────────

async def cmd_cancelar_correo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    correo_id: int,
) -> None:
    """Cancela un correo por ID."""
    if not _es_admin(update):
        return

    if correo_id is None:
        await update.message.reply_text("❌ ID de correo inválido.")
        return

    db = SessionLocal()
    try:
        correo = db.get(Correos, correo_id)
        if not correo:
            await update.message.reply_text(
                f"❌ No se encontró correo con ID {correo_id}."
            )
            return

        if correo.estado in (EstadoCorreo.ENVIADO, EstadoCorreo.CANCELADO):
            await update.message.reply_text(
                f"❌ El correo ID {correo_id} ya está en estado "
                f"`{correo.estado.value}` y no puede cancelarse.",
                parse_mode="Markdown",
            )
            return

        exito = transicionar_estado(correo, EstadoCorreo.CANCELADO, db)
        if exito:
            await update.message.reply_text(
                f"✅ Correo ID {correo_id} cancelado correctamente."
            )
        else:
            await update.message.reply_text(
                f"❌ No se pudo cancelar el correo ID {correo_id}."
            )
    finally:
        db.close()


# ─── Feedback ─────────────────────────────────────────────────────

async def cmd_enviar_feedback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    correo_id: int,
) -> None:
    """Envía feedback para re-redactar un correo."""
    if not _es_admin(update):
        return

    texto_completo = update.message.text.strip()
    _, feedback_texto = extraer_id_y_texto(texto_completo, "/feedback_")

    if correo_id is None or not feedback_texto:
        await update.message.reply_text(
            "❌ Formato incorrecto.\n"
            "Usa: `/feedback_ID tu mensaje aquí`\n\n"
            "Ejemplo: `/feedback_3 Cambia el tono a más formal`",
            parse_mode="Markdown",
        )
        return

    db = SessionLocal()
    try:
        # Verificar límite de intentos
        correo = db.get(Correos, correo_id)
        if correo and correo.intentos_redaccion >= MAX_REWRITE_ATTEMPTS:
            await update.message.reply_text(
                f"❌ Se alcanzó el límite de {MAX_REWRITE_ATTEMPTS} "
                f"intentos de redacción para el correo ID {correo_id}.",
            )
            return

        await update.message.reply_text(
            f"📝 Feedback recibido. Re-redactando correo ID {correo_id}..."
        )

        resultado = aplicar_feedback(correo_id, feedback_texto, db)

        if resultado is None:
            await update.message.reply_text(
                f"❌ No se encontró correo ID {correo_id} en estado "
                "'Esperando Aprobación'."
            )
            return

        correo = resultado.correo

        # Mostrar problemas si los hay
        if resultado.tiene_problemas:
            await update.message.reply_text(
                f"⚠️ *Problemas de resolución:*\n\n{resultado.problemas_resolucion}",
                parse_mode="Markdown",
            )

        # Mostrar nuevo borrador
        resumen = generar_resumen_correo(correo)
        await update.message.reply_text(resumen, parse_mode="Markdown")

    except Exception as e:
        logger.error("Error aplicando feedback: %s", e, exc_info=True)
        await update.message.reply_text(
            f"❌ Error al re-redactar:\n`{str(e)[:300]}`",
            parse_mode="Markdown",
        )
    finally:
        db.close()


# ─── Ver correo ───────────────────────────────────────────────────

async def cmd_ver_correo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    correo_id: int,
) -> None:
    """Muestra el detalle de un correo por ID."""
    if not _es_admin(update):
        return

    if correo_id is None:
        await update.message.reply_text("❌ ID de correo inválido.")
        return

    db = SessionLocal()
    try:
        correo = db.get(Correos, correo_id)
        if not correo:
            await update.message.reply_text(
                f"❌ No se encontró correo con ID {correo_id}."
            )
            return

        etiquetas = {
            EstadoCorreo.NOTA_RECIBIDA: "📝 Nota Recibida",
            EstadoCorreo.REDACTANDO: "✍️ Redactando",
            EstadoCorreo.ESPERANDO_APROBACION: "⏳ Esperando Aprobación",
            EstadoCorreo.ENVIANDO: "📤 Enviando",
            EstadoCorreo.ENVIADO: "✅ Enviado",
            EstadoCorreo.CANCELADO: "❌ Cancelado",
        }
        estado_texto = etiquetas.get(correo.estado, correo.estado.value)

        info = (
            f"📧 *Correo ID {correo.id}*\n\n"
            f"*Estado:* {estado_texto}\n"
            f"*Asunto:* {escapar_markdown(correo.asunto or 'Sin Asunto')}\n"
            f"*Para:* {correo.destinatarios or 'No especificados'}\n"
            f"*Emails:* {correo.destinatarios_email or 'Sin resolver'}\n"
            f"*Adjuntos:* {correo.documentos or 'Ninguno'}\n"
            f"*Creado:* {correo.fecha_creacion.strftime('%Y-%m-%d %H:%M')}\n"
            f"*Intentos:* {correo.intentos_redaccion}\n"
        )

        if correo.feedback_usuario:
            info += (
                f"\n⚠️ *Último feedback:*\n"
                f"_{escapar_markdown(correo.feedback_usuario[:300])}_\n"
            )

        if correo.estado == EstadoCorreo.ENVIADO and correo.fecha_envio:
            info += (
                f"\n📤 Enviado el: "
                f"{correo.fecha_envio.strftime('%Y-%m-%d %H:%M')}\n"
            )

        # Acciones disponibles según estado
        if correo.estado == EstadoCorreo.ESPERANDO_APROBACION:
            info += (
                f"\n━━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ `/enviar_{correo.id}` — Enviar\n"
                f"📝 `/feedback_{correo.id} mensaje` — Cambios\n"
                f"❌ `/cancelar_{correo.id}` — Cancelar"
            )

        await update.message.reply_text(info, parse_mode="Markdown")

        # Si hay cuerpo, enviar como .txt
        if correo.cuerpo and correo.estado == EstadoCorreo.ESPERANDO_APROBACION:
            from utils.generador_txt import generar_txt

            correo_dict = {
                "destinatarios": correo.destinatarios,
                "destinatarios_email": correo.destinatarios_email,
                "asunto": correo.asunto,
                "cuerpo": correo.cuerpo,
            }
            ruta_txt = generar_txt(correo_dict, correo.id)

            with open(ruta_txt, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=f"correo_{correo.id}.txt",
                    caption="📄 Vista previa del correo",
                )

        # Enviar documentos adjuntos si existen
        adjuntos = _obtener_adjuntos_correo(correo, db)
        for documento in adjuntos:
            if Path(documento.ruta).exists():
                with open(documento.ruta, "rb") as doc_file:
                    await update.message.reply_document(
                        document=doc_file,
                        filename=f"{documento.titulo_original}.{documento.tipo}",
                        caption=f"📎 Adjunto: {documento.titulo_original}",
                    )
    finally:
        db.close()


# ─── Enviar correo ────────────────────────────────────────────────

async def cmd_enviar_correo(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    correo_id: int,
) -> None:
    """Aprueba y envía un correo por Gmail API."""
    if not _es_admin(update):
        return

    if correo_id is None:
        await update.message.reply_text("❌ ID de correo inválido.")
        return

    db = SessionLocal()
    try:
        correo = db.get(Correos, correo_id)

        if not correo:
            await update.message.reply_text(
                f"❌ No se encontró correo con ID {correo_id}."
            )
            return

        if correo.estado != EstadoCorreo.ESPERANDO_APROBACION:
            await update.message.reply_text(
                f"❌ El correo ID {correo_id} no está listo para enviarse.\n"
                f"Estado actual: `{correo.estado.value}`",
                parse_mode="Markdown",
            )
            return

        if not correo.destinatarios_email:
            await update.message.reply_text(
                f"❌ El correo ID {correo_id} no tiene destinatarios resueltos.\n"
                "Verifica que los destinatarios estén registrados.",
            )
            return

        # Transicionar a ENVIANDO
        transicionar_estado(correo, EstadoCorreo.ENVIANDO, db)
        await update.message.reply_text(
            f"📤 Enviando correo ID {correo_id}..."
        )

        # Obtener rutas de adjuntos
        adjuntos: list[str] = []
        for documento in _obtener_adjuntos_correo(correo, db):
            if Path(documento.ruta).exists():
                adjuntos.append(documento.ruta)

        # Enviar via Gmail API
        from gmail.sender import enviar_correo_gmail

        enviado = enviar_correo_gmail(
            destinatarios=correo.destinatarios_email,
            asunto=correo.asunto or "Sin asunto",
            cuerpo=correo.cuerpo or "",
            adjuntos=adjuntos,
        )

        if enviado:
            transicionar_estado(correo, EstadoCorreo.ENVIADO, db)
            await update.message.reply_text(
                f"✅ Correo ID {correo_id} enviado correctamente a: "
                f"{correo.destinatarios_email}"
            )
        else:
            # Revertir a ESPERANDO_APROBACION si falla
            transicionar_estado(correo, EstadoCorreo.ESPERANDO_APROBACION, db)
            await update.message.reply_text(
                f"❌ Error al enviar el correo ID {correo_id}.\n"
                "Puedes intentar de nuevo con `/enviar_" + str(correo_id) + "`",
                parse_mode="Markdown",
            )

    except Exception as e:
        db.rollback()
        logger.error("Error enviando correo ID %d: %s", correo_id, e, exc_info=True)
        await update.message.reply_text(
            f"❌ Error inesperado:\n`{str(e)[:300]}`",
            parse_mode="Markdown",
        )
    finally:
        db.close()
