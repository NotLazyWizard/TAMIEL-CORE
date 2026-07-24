"""
bot_telegram/bot.py — Configuración del bot y registro de handlers.

Centraliza la creación de la Application de Telegram
y registra todos los handlers de los submódulos.
"""

import logging
import re

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_CHAT_ID
from bot_telegram.handlers_comandos import (
    cmd_start,
    cmd_estado_correos,
    cmd_tokens,
    cmd_flujo,
)
from bot_telegram.handlers_destinatarios import (
    cmd_destinatarios,
    cmd_nuevo_destinatario,
)
from bot_telegram.handlers_documentos import (
    cmd_documentos,
    cmd_ver_documento,
    cmd_añadir_documento,
    cmd_reprocesar_documento,
)
from bot_telegram.handlers_correo import (
    manejar_nota_voz,
    cmd_cancelar_correo,
    cmd_enviar_feedback,
    cmd_ver_correo,
    cmd_enviar_correo,
)
from utils.helpers import extraer_id

logger = logging.getLogger(__name__)


def crear_aplicacion() -> Application:
    """Crea y configura la Application de Telegram.
    
    Returns:
        Application configurada con todos los handlers registrados.
    
    Raises:
        ValueError: Si TELEGRAM_BOT_TOKEN no está configurado.
    """
    if not TELEGRAM_BOT_TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN no está configurado. Revisa tu archivo .env"
        )

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    _registrar_handlers(app)

    logger.info("Bot de Telegram configurado correctamente.")
    return app


def _registrar_handlers(app: Application) -> None:
    """Registra todos los handlers en la aplicación."""

    # ── Comandos estáticos ────────────────────────────────────────
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("estado_correos", cmd_estado_correos))
    app.add_handler(CommandHandler("tokens", cmd_tokens))
    app.add_handler(CommandHandler("flujo", cmd_flujo))
    app.add_handler(CommandHandler("destinatarios", cmd_destinatarios))
    app.add_handler(CommandHandler("nuevo_destinatario", cmd_nuevo_destinatario))
    app.add_handler(CommandHandler("documentos", cmd_documentos))

    # ── Notas de voz ──────────────────────────────────────────────
    app.add_handler(MessageHandler(filters.VOICE, manejar_nota_voz))

    # ── Documentos adjuntos con caption /añadir_documento ─────────
    app.add_handler(MessageHandler(
        filters.Document.ALL & filters.CaptionRegex(r"^/añadir_documento"),
        cmd_añadir_documento,
    ))

    # ── Comandos dinámicos (con ID) ───────────────────────────────
    app.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r"^/(cancelar|feedback|correo|enviar|documento|reprocesar)_\d+"),
        _manejar_comando_dinamico,
    ))

    logger.info("Handlers registrados: %d", len(app.handlers.get(0, [])))


async def _manejar_comando_dinamico(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Router para comandos dinámicos con ID: /cancelar_X, /feedback_X, etc."""
    if update.effective_chat.id != TELEGRAM_ADMIN_CHAT_ID:
        return

    texto = update.message.text.strip()

    if texto.startswith("/cancelar_"):
        correo_id = extraer_id(texto, "/cancelar_")
        await cmd_cancelar_correo(update, context, correo_id)

    elif texto.startswith("/feedback_"):
        correo_id = extraer_id(texto, "/feedback_")
        await cmd_enviar_feedback(update, context, correo_id)

    elif texto.startswith("/correo_"):
        correo_id = extraer_id(texto, "/correo_")
        await cmd_ver_correo(update, context, correo_id)

    elif texto.startswith("/enviar_"):
        correo_id = extraer_id(texto, "/enviar_")
        await cmd_enviar_correo(update, context, correo_id)

    elif texto.startswith("/documento_"):
        doc_id = extraer_id(texto, "/documento_")
        await cmd_ver_documento(update, context, doc_id)

    elif texto.startswith("/reprocesar_"):
        doc_id = extraer_id(texto, "/reprocesar_")
        await cmd_reprocesar_documento(update, context, doc_id)
