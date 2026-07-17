"""
telegram/handlers_destinatarios.py — Handlers para gestión de destinatarios.

Comandos: /destinatarios, /nuevo_destinatario
"""

import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from config.database import SessionLocal, Destinatarios
from config.settings import TELEGRAM_ADMIN_CHAT_ID

logger = logging.getLogger(__name__)


def _es_admin(update: Update) -> bool:
    return update.effective_chat.id == TELEGRAM_ADMIN_CHAT_ID


async def cmd_destinatarios(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la lista de destinatarios guardados."""
    if not _es_admin(update):
        return

    db = SessionLocal()
    try:
        destinatarios = db.query(Destinatarios).order_by(Destinatarios.nombre).all()

        if not destinatarios:
            await update.message.reply_text(
                "📭 No hay destinatarios guardados.\n"
                "Usa `/nuevo_destinatario nombre correo` para agregar uno.",
                parse_mode="Markdown",
            )
            return

        LIMITE_TELEGRAM = 3500
        encabezado = "👤 *Destinatarios Guardados:*\n\n"
        texto = encabezado

        for dest in destinatarios:
            linea = f"• ID `{dest.id}` — {dest.nombre} (`{dest.correo}`)\n"

            if len(texto) + len(linea) > LIMITE_TELEGRAM:
                await update.message.reply_text(texto, parse_mode="Markdown")
                texto = encabezado

            texto += linea

        if texto.strip() != encabezado.strip():
            await update.message.reply_text(texto, parse_mode="Markdown")
    finally:
        db.close()


async def cmd_nuevo_destinatario(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Agrega un nuevo destinatario: /nuevo_destinatario nombre correo"""
    if not _es_admin(update):
        return

    texto_completo = update.message.text.strip()

    # Parsear: /nuevo_destinatario <nombre> <correo>
    # El correo siempre es la última palabra (contiene @)
    match = re.match(
        r"/nuevo_destinatario\s+(.+?)\s+([\w.+-]+@[\w.-]+\.\w+)$",
        texto_completo,
        re.IGNORECASE,
    )
    if not match:
        await update.message.reply_text(
            "❌ Formato incorrecto.\n"
            "Usa: `/nuevo_destinatario nombre correo@ejemplo.com`",
            parse_mode="Markdown",
        )
        return

    nombre = match.group(1).strip()
    correo_email = match.group(2).strip()

    db = SessionLocal()
    try:
        # Verificar duplicados
        existente = db.query(Destinatarios).filter(
            Destinatarios.correo == correo_email
        ).first()

        if existente:
            await update.message.reply_text(
                f"❌ El correo `{correo_email}` ya está registrado "
                f"como \"{existente.nombre}\".",
                parse_mode="Markdown",
            )
            return

        nuevo = Destinatarios(nombre=nombre, correo=correo_email)
        db.add(nuevo)
        db.commit()
        db.refresh(nuevo)

        await update.message.reply_text(
            f"✅ Destinatario agregado:\n"
            f"• ID: `{nuevo.id}`\n"
            f"• Nombre: {nombre}\n"
            f"• Correo: `{correo_email}`",
            parse_mode="Markdown",
        )
        logger.info("Nuevo destinatario: %s (%s)", nombre, correo_email)
    finally:
        db.close()
