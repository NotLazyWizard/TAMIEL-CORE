"""
telegram/handlers_documentos.py — Handlers para gestión de documentos.

Comandos: /documentos, /documento_ID, /reprocesar_ID
Wizard conversacional: /añadir_documento (3 pasos guiados)
"""

import asyncio
import logging
import uuid
from pathlib import Path

from telegram import Update
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from config.database import SessionLocal, Documentos, EstadoDocumento
from config.settings import TELEGRAM_ADMIN_CHAT_ID, DOCUMENTOS_DIR, EXTENSIONES_PERMITIDAS
from services import document_repository as doc_repo
from services.document_service import calcular_sha256, detectar_mime_type, obtener_tamano

logger = logging.getLogger(__name__)


# ─── Estados del wizard de incorporación ──────────────────────────

ESPERANDO_DOCUMENTO = 0
ESPERANDO_NOMBRE_DOCUMENTO = 1


def _es_admin(update: Update) -> bool:
    return update.effective_chat.id == TELEGRAM_ADMIN_CHAT_ID


# ─── Consultas de documentos (sin cambios) ────────────────────────

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
                "Usa `/añadir_documento` para iniciar el proceso.",
                parse_mode="Markdown",
            )
            return

        LIMITE_TELEGRAM = 3500
        encabezado = "📎 *Documentos Disponibles:*\n\n"
        texto = encabezado

        # Etiquetas de estado
        iconos_estado = {
            EstadoDocumento.PENDIENTE.value: "⏳",
            EstadoDocumento.PROCESANDO.value: "⚙️",
            EstadoDocumento.COMPLETADO.value: "✅",
            EstadoDocumento.ERROR.value: "❌",
        }

        for doc in documentos:
            icono = iconos_estado.get(doc.estado, "📄")
            linea = f"• {icono} ID `{doc.id}` — {doc.titulo_original} (`.{doc.tipo}`)\n"

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
    """Muestra y envía un documento por su ID, incluyendo estado de procesamiento."""
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

        # Información extendida del documento
        iconos_estado = {
            EstadoDocumento.PENDIENTE.value: "⏳ Pendiente",
            EstadoDocumento.PROCESANDO.value: "⚙️ Procesando",
            EstadoDocumento.COMPLETADO.value: "✅ Procesado",
            EstadoDocumento.ERROR.value: "❌ Error",
        }
        estado_texto = iconos_estado.get(documento.estado, documento.estado or "Desconocido")

        info = (
            f"📎 *Documento ID {documento.id}*\n\n"
            f"*Título:* {documento.titulo_original}\n"
            f"*Tipo:* `.{documento.tipo}`\n"
            f"*Estado:* {estado_texto}\n"
        )

        if documento.tamano_bytes:
            tamano_kb = documento.tamano_bytes / 1024
            info += f"*Tamaño:* {tamano_kb:.1f} KB\n"

        if documento.sha256:
            info += f"*SHA256:* `{documento.sha256[:16]}...`\n"

        # Mostrar resumen si está procesado
        conocimiento = doc_repo.obtener_conocimiento(db, documento_id)
        if conocimiento and conocimiento.resumen:
            resumen_corto = conocimiento.resumen[:300]
            info += f"\n🧠 *Resumen:*\n_{resumen_corto}_\n"

            if conocimiento.tipo_documento:
                info += f"*Tipo detectado:* {conocimiento.tipo_documento}\n"

        # Error de procesamiento
        if documento.error_procesamiento:
            info += f"\n⚠️ *Error:* `{documento.error_procesamiento[:200]}`\n"
            info += f"Usa `/reprocesar_{documento.id}` para reintentar.\n"

        await update.message.reply_text(info, parse_mode="Markdown")

        # Enviar el archivo
        with open(ruta, "rb") as doc_file:
            await update.message.reply_document(
                document=doc_file,
                filename=f"{documento.titulo_original}.{documento.tipo}",
                caption=f"📎 Documento ID {documento.id}",
            )
    finally:
        db.close()


# ─── Wizard conversacional: /añadir_documento ────────────────────

async def wizard_inicio(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Paso 1: Inicia el wizard y solicita el archivo.

    Transición: IDLE → ESPERANDO_DOCUMENTO
    """
    if not _es_admin(update):
        return ConversationHandler.END

    await update.message.reply_text(
        "📄 Entendido.\n"
        "Ahora envíame el documento que deseas almacenar.\n\n"
        "_(Usa /cancelar en cualquier momento para abortar)_",
        parse_mode="Markdown",
    )

    logger.info("Wizard de documento iniciado por el admin.")
    return ESPERANDO_DOCUMENTO


async def wizard_recibir_documento(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Paso 2: Recibe el archivo, lo guarda temporalmente, pide el nombre.

    Transición: ESPERANDO_DOCUMENTO → ESPERANDO_NOMBRE_DOCUMENTO

    El archivo se descarga a DOCUMENTOS_DIR con un nombre temporal UUID.
    No se registra en la base de datos aún.
    No se ejecuta el parser ni el KnowledgeExtractor.
    """
    documento = update.message.document

    if documento is None:
        await update.message.reply_text(
            "❌ Eso no es un archivo.\n"
            "Por favor envíame un documento como archivo adjunto.\n\n"
            "_(Usa /cancelar para abortar)_",
            parse_mode="Markdown",
        )
        return ESPERANDO_DOCUMENTO

    # Obtener extensión y validar
    nombre_original = documento.file_name or "archivo"
    extension = Path(nombre_original).suffix.lstrip(".").lower()

    if extension not in EXTENSIONES_PERMITIDAS:
        await update.message.reply_text(
            f"❌ Extensión `.{extension}` no soportada.\n"
            f"Extensiones permitidas: {', '.join(sorted(EXTENSIONES_PERMITIDAS))}\n\n"
            "Envía otro archivo o usa /cancelar para abortar.",
            parse_mode="Markdown",
        )
        return ESPERANDO_DOCUMENTO

    # Descargar temporalmente
    DOCUMENTOS_DIR.mkdir(parents=True, exist_ok=True)
    nombre_temporal = f"{uuid.uuid4()}.{extension}"
    ruta_temporal = DOCUMENTOS_DIR / nombre_temporal

    archivo_tg = await documento.get_file()
    await archivo_tg.download_to_drive(custom_path=str(ruta_temporal))

    # Guardar datos temporales en context.user_data
    context.user_data["wizard_doc"] = {
        "ruta_temporal": str(ruta_temporal),
        "nombre_temporal": nombre_temporal,
        "extension": extension,
        "nombre_original_tg": nombre_original,
    }

    logger.info(
        "Documento recibido temporalmente: %s (%s) → %s",
        nombre_original, extension, ruta_temporal,
    )

    await update.message.reply_text(
        "✅ Documento recibido correctamente.\n\n"
        "Ahora dime con qué nombre deseas almacenarlo dentro del sistema.\n\n"
        "_(Escribe el nombre o usa /cancelar para abortar)_",
        parse_mode="Markdown",
    )

    return ESPERANDO_NOMBRE_DOCUMENTO


async def wizard_recibir_nombre(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Paso 3: Recibe el nombre, registra el documento y lanza el pipeline.

    Transición: ESPERANDO_NOMBRE_DOCUMENTO → IDLE (ConversationHandler.END)
    """
    titulo_original = update.message.text.strip()

    # Validar nombre no vacío
    if not titulo_original:
        await update.message.reply_text(
            "❌ El nombre no puede estar vacío.\n"
            "Escribe un nombre para el documento o usa /cancelar.",
        )
        return ESPERANDO_NOMBRE_DOCUMENTO

    # Validar que no sea un comando
    if titulo_original.startswith("/"):
        await update.message.reply_text(
            "❌ El nombre no puede ser un comando.\n"
            "Escribe un nombre descriptivo para el documento.",
        )
        return ESPERANDO_NOMBRE_DOCUMENTO

    # Recuperar datos temporales
    datos_temp = context.user_data.get("wizard_doc")
    if not datos_temp:
        await update.message.reply_text(
            "❌ No hay un documento pendiente de nombrar.\n"
            "Usa `/añadir_documento` para iniciar el proceso.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    ruta_temporal = Path(datos_temp["ruta_temporal"])
    nombre_temporal = datos_temp["nombre_temporal"]
    extension = datos_temp["extension"]

    # Verificar que el archivo temporal siga existiendo
    if not ruta_temporal.exists():
        await update.message.reply_text(
            "❌ El archivo temporal se perdió. Inicia el proceso de nuevo con "
            "`/añadir_documento`.",
            parse_mode="Markdown",
        )
        context.user_data.pop("wizard_doc", None)
        return ConversationHandler.END

    db = SessionLocal()
    try:
        # Validar que el nombre lógico no exista
        existente = db.query(Documentos).filter(
            Documentos.titulo_original == titulo_original
        ).first()

        if existente:
            await update.message.reply_text(
                f"❌ Ya existe un documento con el nombre \"{titulo_original}\".\n"
                f"ID existente: `{existente.id}`\n\n"
                "Escribe un nombre diferente o usa /cancelar.",
                parse_mode="Markdown",
            )
            return ESPERANDO_NOMBRE_DOCUMENTO

        # ── Ahora sí: registrar definitivamente ──────────────────

        # Calcular metadatos físicos
        sha256 = calcular_sha256(ruta_temporal)
        mime_type = detectar_mime_type(ruta_temporal)
        tamano = obtener_tamano(ruta_temporal)

        # Registrar en DB
        nuevo_doc = doc_repo.crear_documento(
            db,
            titulo_original=titulo_original,
            titulo_guardado=nombre_temporal,
            extension=extension,
            ruta=str(ruta_temporal),
            mime_type=mime_type,
            tamano_bytes=tamano,
            sha256=sha256,
        )

        await update.message.reply_text(
            f"✅ Documento \"{titulo_original}\" almacenado correctamente.\n\n"
            f"• ID: `{nuevo_doc.id}`\n"
            f"• Tipo: `.{extension}`\n"
            f"• Tamaño: {tamano / 1024:.1f} KB\n\n"
            f"🧠 Procesando contenido en segundo plano...",
            parse_mode="Markdown",
        )

        logger.info(
            "Documento registrado vía wizard: '%s' (%s) → ID %d",
            titulo_original, extension, nuevo_doc.id,
        )

        # Limpiar datos temporales
        context.user_data.pop("wizard_doc", None)

        # Lanzar procesamiento asíncrono (no bloquea)
        doc_id = nuevo_doc.id
        chat_id = update.effective_chat.id

        async def _procesar_y_notificar():
            from services.document_pipeline import procesar_documento
            exito = await procesar_documento(doc_id)
            try:
                if exito:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"🧠 Documento ID `{doc_id}` procesado exitosamente.\n"
                            f"Usa `/documento_{doc_id}` para ver el resumen."
                        ),
                        parse_mode="Markdown",
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"⚠️ Error procesando documento ID `{doc_id}`.\n"
                            f"Usa `/reprocesar_{doc_id}` para reintentar."
                        ),
                        parse_mode="Markdown",
                    )
            except Exception as e:
                logger.error("Error enviando notificación de procesamiento: %s", e)

        asyncio.create_task(_procesar_y_notificar())

    finally:
        db.close()

    return ConversationHandler.END


async def wizard_cancelar(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Cancela el wizard en cualquier etapa.

    Limpia el archivo temporal y el estado de la conversación.
    """
    # Limpiar archivo temporal si existe
    datos_temp = context.user_data.pop("wizard_doc", None)
    if datos_temp:
        ruta_temporal = Path(datos_temp["ruta_temporal"])
        if ruta_temporal.exists():
            try:
                ruta_temporal.unlink()
                logger.info("Archivo temporal eliminado: %s", ruta_temporal)
            except OSError as e:
                logger.warning("Error eliminando archivo temporal: %s", e)

    await update.message.reply_text(
        "🚫 Operación cancelada. El archivo temporal fue eliminado.\n"
        "Puedes iniciar de nuevo con `/añadir_documento` cuando quieras.",
        parse_mode="Markdown",
    )

    return ConversationHandler.END


async def wizard_mensaje_inesperado(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> int:
    """Maneja mensajes inesperados durante ESPERANDO_DOCUMENTO.

    Si el usuario envía texto en vez de un archivo, se le recuerda.
    """
    await update.message.reply_text(
        "❌ Esperaba un archivo, no un mensaje de texto.\n"
        "Por favor envíame el documento como archivo adjunto.\n\n"
        "_(Usa /cancelar para abortar)_",
        parse_mode="Markdown",
    )
    return ESPERANDO_DOCUMENTO


def crear_wizard_documento() -> ConversationHandler:
    """Crea y retorna el ConversationHandler para el wizard de documentos.

    Este ConversationHandler gestiona la máquina de estados:
        IDLE → ESPERANDO_DOCUMENTO → ESPERANDO_NOMBRE_DOCUMENTO → IDLE

    La infraestructura de ConversationHandler de python-telegram-bot
    maneja el estado per-user/per-chat automáticamente, sin variables globales.
    """
    return ConversationHandler(
        entry_points=[
            # CommandHandler no acepta caracteres no-ASCII (ñ),
            # así que usamos MessageHandler con Regex.
            MessageHandler(
                filters.TEXT & filters.Regex(r"^/añadir_documento"),
                wizard_inicio,
            ),
        ],
        states={
            ESPERANDO_DOCUMENTO: [
                MessageHandler(filters.Document.ALL, wizard_recibir_documento),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    wizard_mensaje_inesperado,
                ),
            ],
            ESPERANDO_NOMBRE_DOCUMENTO: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    wizard_recibir_nombre,
                ),
            ],
        },
        fallbacks=[
            MessageHandler(
                filters.TEXT & filters.Regex(r"^/cancelar$"),
                wizard_cancelar,
            ),
        ],
        conversation_timeout=300,  # 5 minutos de inactividad → cancelar
        name="wizard_documento",
        persistent=False,
    )


# ─── Reprocesar documento ─────────────────────────────────────────

async def cmd_reprocesar_documento(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    documento_id: int,
) -> None:
    """Reprocesa un documento que falló previamente."""
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

        await update.message.reply_text(
            f"🔄 Reprocesando documento ID `{documento_id}`...",
            parse_mode="Markdown",
        )

        chat_id = update.effective_chat.id
        doc_id = documento_id

        async def _reprocesar_y_notificar():
            from services.document_pipeline import reprocesar_documento
            exito = await reprocesar_documento(doc_id)
            try:
                if exito:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=(
                            f"✅ Documento ID `{doc_id}` reprocesado exitosamente.\n"
                            f"Usa `/documento_{doc_id}` para ver el resumen."
                        ),
                        parse_mode="Markdown",
                    )
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Falló el reprocesamiento del documento ID `{doc_id}`.",
                        parse_mode="Markdown",
                    )
            except Exception as e:
                logger.error("Error enviando notificación de reprocesamiento: %s", e)

        asyncio.create_task(_reprocesar_y_notificar())

    finally:
        db.close()
