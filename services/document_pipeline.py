"""
services/document_pipeline.py — Pipeline de procesamiento de documentos.

Orquesta las etapas del procesamiento de forma asíncrona:
    1. Extraer texto (ParserService)
    2. Guardar contenido completo (DocumentRepository)
    3. Guardar páginas (DocumentRepository)
    4. Extraer conocimiento (KnowledgeExtractor)
    5. Guardar conocimiento (DocumentRepository)
    6. Actualizar estado

No bloquea el bot de Telegram. Si falla, registra el error
y permite reprocesamiento posterior.
"""

import asyncio
import hashlib
import json
import logging
from pathlib import Path

from config.database import SessionLocal, EstadoDocumento
from config.settings import GROQ_MODEL_KNOWLEDGE, DOC_PROCESSING_ENABLED
from services import document_repository as repo
from services.parser_service import ParserService

logger = logging.getLogger(__name__)


async def procesar_documento(doc_id: int) -> bool:
    """Pipeline completo de procesamiento de un documento.

    Ejecuta todas las etapas secuencialmente. Si falla en cualquier
    punto, registra el error y no elimina el archivo.

    Args:
        doc_id: ID del documento a procesar.

    Returns:
        True si el procesamiento fue exitoso, False si hubo error.
    """
    if not DOC_PROCESSING_ENABLED:
        logger.info("Procesamiento de documentos deshabilitado. Omitiendo doc ID %d.", doc_id)
        return False

    logger.info("═══ Iniciando pipeline para documento ID %d ═══", doc_id)

    db = SessionLocal()
    try:
        # 1. Obtener documento
        documento = repo.obtener_documento(db, doc_id)
        if not documento:
            logger.error("Documento ID %d no encontrado.", doc_id)
            return False

        ruta = Path(documento.ruta)
        if not ruta.exists():
            repo.actualizar_estado(db, doc_id, EstadoDocumento.ERROR,
                                   error=f"Archivo no encontrado: {documento.ruta}")
            return False

        # 2. Marcar como procesando
        repo.actualizar_estado(db, doc_id, EstadoDocumento.PROCESANDO)

        # 3. Extraer texto
        logger.info("Etapa 1/3: Extrayendo texto de '%s'...", documento.titulo_original)
        extension = documento.extension or documento.tipo or ""

        # Ejecutar parser en thread para no bloquear el event loop
        resultado_parse = await asyncio.to_thread(
            ParserService.extraer_contenido, ruta, extension,
        )

        if not resultado_parse.texto_completo.strip():
            repo.actualizar_estado(db, doc_id, EstadoDocumento.ERROR,
                                   error="No se pudo extraer texto del documento.")
            logger.warning("Documento ID %d: sin texto extraíble.", doc_id)
            return False

        # 4. Guardar contenido completo
        hash_contenido = hashlib.sha256(
            resultado_parse.texto_completo.encode("utf-8")
        ).hexdigest()

        repo.guardar_contenido(
            db, doc_id,
            texto_completo=resultado_parse.texto_completo,
            idioma=resultado_parse.idioma,
            num_paginas=resultado_parse.num_paginas,
            parser_utilizado=resultado_parse.parser_utilizado,
            hash_contenido=hash_contenido,
        )

        # 5. Guardar páginas
        paginas_dict = [
            {
                "numero_pagina": p.numero_pagina,
                "texto": p.texto,
                "hash_pagina": p.hash_pagina,
            }
            for p in resultado_parse.paginas
        ]
        repo.guardar_paginas(db, doc_id, paginas_dict)

        # 6. Extraer conocimiento con LLM
        logger.info("Etapa 2/3: Extrayendo conocimiento con LLM...")

        try:
            knowledge_result = await asyncio.to_thread(
                _extraer_conocimiento_sync,
                resultado_parse.texto_completo,
                documento.titulo_original,
            )

            # 7. Guardar conocimiento
            repo.guardar_conocimiento(
                db, doc_id,
                resumen=knowledge_result.resumen,
                tipo_documento=knowledge_result.tipo_documento,
                json_llm=knowledge_result.json_completo,
                modelo=knowledge_result.modelo,
                version_prompt=knowledge_result.version_prompt,
            )

        except Exception as e:
            # Si falla la extracción de conocimiento, no es fatal
            # El texto ya fue guardado exitosamente
            logger.warning(
                "Documento ID %d: extracción de conocimiento falló (%s). "
                "Texto guardado correctamente.", doc_id, e,
            )

        # 8. Marcar como completado
        logger.info("Etapa 3/3: Finalizando procesamiento...")
        repo.marcar_procesado(db, doc_id)

        logger.info(
            "═══ Pipeline completado para documento ID %d: '%s' "
            "(%d páginas, parser: %s) ═══",
            doc_id, documento.titulo_original,
            resultado_parse.num_paginas,
            resultado_parse.parser_utilizado,
        )
        return True

    except Exception as e:
        logger.error(
            "Error en pipeline para documento ID %d: %s", doc_id, e, exc_info=True,
        )
        try:
            repo.actualizar_estado(
                db, doc_id, EstadoDocumento.ERROR,
                error=f"{type(e).__name__}: {str(e)[:500]}",
            )
        except Exception:
            logger.error("Error adicional actualizando estado del documento ID %d.", doc_id)
        return False

    finally:
        db.close()


def _extraer_conocimiento_sync(texto: str, titulo: str):
    """Wrapper síncrono para la extracción de conocimiento.

    Se ejecuta en un thread separado via asyncio.to_thread().
    """
    from ai.groq_provider import GroqLLMProvider
    from ai.knowledge_extractor import KnowledgeExtractor

    provider = GroqLLMProvider(model=GROQ_MODEL_KNOWLEDGE)
    extractor = KnowledgeExtractor(provider)
    return extractor.extraer_conocimiento(texto, titulo)


async def reprocesar_documento(doc_id: int) -> bool:
    """Reprocesa un documento que falló previamente.

    Limpia el estado de error y ejecuta el pipeline completo.

    Args:
        doc_id: ID del documento a reprocesar.

    Returns:
        True si el reprocesamiento fue exitoso.
    """
    logger.info("Reprocesando documento ID %d...", doc_id)

    db = SessionLocal()
    try:
        documento = repo.obtener_documento(db, doc_id)
        if not documento:
            logger.error("Documento ID %d no encontrado para reprocesar.", doc_id)
            return False

        # Resetear estado
        repo.actualizar_estado(db, doc_id, EstadoDocumento.PENDIENTE)
    finally:
        db.close()

    return await procesar_documento(doc_id)
