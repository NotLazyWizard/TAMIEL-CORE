"""
telegram/handlers_documentos.py — Handlers para gestión de documentos.

Comandos: /documentos, /documento_ID, /añadir_documento
"""

import logging
import uuid
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from config.database import SessionLocal, Documentos
from config.settings import TELEGRAM_ADMIN_CHAT_ID, DOCUMENTOS_DIR, EXTENSIONES_PERMITIDAS

logger = logging.getLogger(__name__)


def _es_admin(update: Update) -> bool:
    return update.effective_chat.id == TELEGRAM_ADMIN_CHAT_ID


async def cmd_documentos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Muestra la lista de documentos disponibles."""
    if not _es_admin(update):
        return

    db = SessionLocal()
    try:
        documentos = db.query(Documentos).order_by(Documentos.titulo_original).all()

        if not documentos:
            await update.message.reply_text(
                "📭 No hay documentos guardados.\n"
                "Usa `/añadir_documento titulo tipo` con un archivo adjunto.",
                parse_mode="Markdown",
            )
            return

        LIMITE_TELEGRAM = 3500
        encabezado = "📎 *Documentos Disponibles:*\n\n"
        texto = encabezado

        for doc in documentos:
            linea = f"• ID `{doc.id}` — {doc.titulo_original} (`.{doc.tipo}`)\n"

            if len(texto) + len(linea) > LIMITE_TELEGRAM:
                await update.message.reply_text(texto, parse_mode="Markdown")
                texto = encabezado

            texto += linea

        if texto.strip() != encabezado.strip():
            await update.message.reply_text(texto, parse_mode="Markdown")
    finally:
        db.close()


async def cmd_ver_documento(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    documento_id: int,
) -> None:
    """Muestra y envía un documento por su ID."""
    if not _es_admin(update):
        return

    if documento_id is None:
        await update.message.reply_text("❌ ID de documento inválido.")
        return

    db = SessionLocal()
    try:
        documento = db.get(Documentos, documento_id)
        if not documento:
            await update.message.reply_text(
                f"❌ No se encontró documento con ID {documento_id}."
            )
            return

        ruta = Path(documento.ruta)
        if not ruta.exists():
            await update.message.reply_text(
                f"❌ El archivo físico no se encontró en: `{documento.ruta}`",
                parse_mode="Markdown",
            )
            return

        with open(ruta, "rb") as doc_file:
            await update.message.reply_document(
                document=doc_file,
                filename=f"{documento.titulo_original}.{documento.tipo}",
                caption=(
                    f"📎 Documento ID {documento.id}\n"
                    f"Título: {documento.titulo_original}\n"
                    f"Tipo: {documento.tipo}"
                ),
            )
    finally:
        db.close()


async def cmd_añadir_documento(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Agrega un documento: /añadir_documento titulo_logico + archivo adjunto.
    
    El tipo se detecta automáticamente de la extensión del archivo.
    """
    if not _es_admin(update):
        return

    texto_completo = update.message.text or update.message.caption or ""
    texto_completo = texto_completo.strip()

    # Extraer título lógico del comando
    partes = texto_completo.split(maxsplit=1)
    if len(partes) < 2 or not partes[1].strip():
        await update.message.reply_text(
            "❌ Formato incorrecto.\n"
            "Usa: `/añadir_documento Nombre del documento` adjuntando el archivo.\n\n"
            "Ejemplo: `/añadir_documento Reporte Mensual` + adjuntar PDF",
            parse_mode="Markdown",
        )
        return

    titulo_original = partes[1].strip()

    # Verificar que hay un archivo adjunto
    documento = update.message.document

    if documento is None:
        await update.message.reply_text(
            "❌ Debes adjuntar un archivo junto con el comando.\n"
            "Envía el archivo con el caption: `/añadir_documento Nombre del documento`",
            parse_mode="Markdown",
        )
        return

    # Obtener extensión y validar
    nombre_original = documento.file_name or "archivo"
    extension = Path(nombre_original).suffix.lstrip(".").lower()

    if extension not in EXTENSIONES_PERMITIDAS:
        await update.message.reply_text(
            f"❌ Extensión `.{extension}` no soportada.\n"
            f"Extensiones permitidas: {', '.join(sorted(EXTENSIONES_PERMITIDAS))}",
            parse_mode="Markdown",
        )
        return

    db = SessionLocal()
    try:
        # Verificar que el nombre lógico no exista
        existente = db.query(Documentos).filter(
            Documentos.titulo_original == titulo_original
        ).first()

        if existente:
            await update.message.reply_text(
                f"❌ Ya existe un documento con el nombre \"{titulo_original}\".\n"
                f"ID existente: `{existente.id}`",
                parse_mode="Markdown",
            )
            return

        # Descargar y guardar
        DOCUMENTOS_DIR.mkdir(parents=True, exist_ok=True)
        nombre_guardado = f"{uuid.uuid4()}.{extension}"
        ruta_guardado = DOCUMENTOS_DIR / nombre_guardado

        archivo_tg = await documento.get_file()
        await archivo_tg.download_to_drive(custom_path=str(ruta_guardado))

        # Registrar en DB
        nuevo_doc = Documentos(
            titulo_original=titulo_original,
            titulo_guardado=nombre_guardado,
            tipo=extension,
            ruta=str(ruta_guardado),
        )
        db.add(nuevo_doc)
        db.commit()
        db.refresh(nuevo_doc)

        await update.message.reply_text(
            f"✅ Documento guardado:\n"
            f"• ID: `{nuevo_doc.id}`\n"
            f"• Título: {titulo_original}\n"
            f"• Tipo: `.{extension}`\n"
            f"• Archivo: `{nombre_guardado}`",
            parse_mode="Markdown",
        )
        logger.info(
            "Documento agregado: %s (%s) → %s",
            titulo_original, extension, ruta_guardado,
        )
    finally:
        db.close()
