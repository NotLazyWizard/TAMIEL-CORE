"""
telegram/handlers_comandos.py — Handlers de comandos generales.

Comandos: /start, /estado_correos, /tokens, /flujo
"""

import logging
import os
import re

from telegram import Update
from telegram.ext import ContextTypes
from groq import Groq

from config.database import SessionLocal, Correos, EstadoCorreo
from config.settings import TELEGRAM_ADMIN_CHAT_ID, GROQ_API_KEY, GROQ_MODEL_REDACTOR
from utils.helpers import escapar_markdown

logger = logging.getLogger(__name__)


def _es_admin(update: Update) -> bool:
    """Verifica si el usuario es el administrador autorizado."""
    return update.effective_chat.id == TELEGRAM_ADMIN_CHAT_ID


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el menú de comandos disponibles."""
    await update.message.reply_text(
        "🤖 *Tamiel Activo*\n\n"
        "📧 *Correos:*\n"
        "• Envía una nota de voz para redactar un correo\n"
        "• `/estado_correos` — Ver correos activos\n"
        "• `/correo_ID` — Ver detalle de un correo\n"
        "• `/enviar_ID` — Enviar correo aprobado\n"
        "• `/feedback_ID mensaje` — Solicitar cambios\n"
        "• `/cancelar_ID` — Cancelar correo\n\n"
        "👤 *Destinatarios:*\n"
        "• `/destinatarios` — Ver contactos guardados\n"
        "• `/nuevo_destinatario nombre correo` — Agregar contacto\n\n"
        "📎 *Documentos:*\n"
        "• `/documentos` — Ver documentos disponibles\n"
        "• `/documento_ID` — Ver/descargar documento\n"
        "• `/añadir_documento titulo tipo` + archivo adjunto\n\n"
        "⚙️ *Sistema:*\n"
        "• `/tokens` — Verificar cuota de Groq\n"
        "• `/flujo` — Ver flujo del sistema\n",
        parse_mode="Markdown",
    )


async def cmd_estado_correos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el estado de los correos activos."""
    if not _es_admin(update):
        return

    db = SessionLocal()
    try:
        estados_activos = [
            EstadoCorreo.NOTA_RECIBIDA,
            EstadoCorreo.REDACTANDO,
            EstadoCorreo.ESPERANDO_APROBACION,
            EstadoCorreo.ENVIANDO,
            EstadoCorreo.ENVIADO,
        ]
        correos = db.query(Correos).filter(
            Correos.estado.in_(estados_activos)
        ).order_by(Correos.fecha_creacion.desc()).all()

        if not correos:
            await update.message.reply_text("📭 No hay correos activos en este momento.")
            return

        LIMITE_TELEGRAM = 3500
        encabezado = "📬 *Estado de Correos Activos:*\n\n"
        texto = encabezado

        etiquetas = {
            EstadoCorreo.NOTA_RECIBIDA: "📝",
            EstadoCorreo.REDACTANDO: "✍️",
            EstadoCorreo.ESPERANDO_APROBACION: "⏳",
            EstadoCorreo.ENVIANDO: "📤",
            EstadoCorreo.ENVIADO: "✅",
        }

        for correo in correos:
            icono = etiquetas.get(correo.estado, "❓")
            asunto_seguro = escapar_markdown(correo.asunto or "Sin Asunto")
            linea = (
                f"• {icono} ID `{correo.id}` — {asunto_seguro}\n"
                f"  Estado: `{correo.estado.value}`\n\n"
            )

            if len(texto) + len(linea) > LIMITE_TELEGRAM:
                await update.message.reply_text(texto, parse_mode="Markdown")
                texto = encabezado

            texto += linea

        if texto.strip() != encabezado.strip():
            await update.message.reply_text(texto, parse_mode="Markdown")
    finally:
        db.close()


async def cmd_tokens(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Verifica si hay cuota de Groq disponible con una petición mínima."""
    if not _es_admin(update):
        return

    await update.message.reply_text("🔍 Verificando cuota de Groq...")

    try:
        client = Groq(api_key=GROQ_API_KEY)
        client.chat.completions.create(
            model=GROQ_MODEL_REDACTOR,
            messages=[{"role": "user", "content": "hola"}],
            max_tokens=5,
        )
        await update.message.reply_text(
            "✅ Hay cuota disponible. El sistema puede redactar correos normalmente."
        )
    except Exception as e:
        error_texto = str(e)
        if "rate_limit_exceeded" in error_texto or "429" in error_texto:
            match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", error_texto)
            if match:
                minutos = int(match.group(1)) if match.group(1) else 0
                segundos = float(match.group(2))
                total_min = max(1, round((minutos * 60 + segundos) / 60))
                await update.message.reply_text(
                    f"⏳ No hay cuota disponible.\n"
                    f"Se restablecerá en ~{total_min} minuto{'s' if total_min != 1 else ''}."
                )
            else:
                await update.message.reply_text(
                    "⏳ No hay cuota disponible (límite alcanzado)."
                )
        else:
            await update.message.reply_text(
                f"❌ Error al verificar: {error_texto[:200]}"
            )


async def cmd_flujo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra el flujo del sistema de correos."""
    if not _es_admin(update):
        return

    await update.message.reply_text(
        "🔄 *Flujo del Sistema*\n\n"
        "1️⃣ Envías una *nota de voz* por Telegram\n"
        "2️⃣ El audio se *transcribe* automáticamente (Groq/Whisper)\n"
        "3️⃣ El texto se *redacta* como correo profesional (Groq/LLM)\n"
        "4️⃣ Python *resuelve* nombres → emails y documentos → archivos\n"
        "5️⃣ Recibes un *borrador* para revisar\n"
        "6️⃣ Puedes *aprobar*, *solicitar cambios* o *cancelar*\n"
        "7️⃣ Al aprobar, se *envía* por Gmail API\n\n"
        "💡 Puedes iterar el borrador con `/feedback_ID` las veces que necesites.",
        parse_mode="Markdown",
    )
