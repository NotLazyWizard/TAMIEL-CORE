"""
services/document_repository.py — Repositorio documental.

Capa de persistencia que encapsula todo acceso a SQLite
para el subsistema de documentos.
Nunca interpreta contenido. Solo persiste datos.
"""

import json
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from config.database import (
    Documentos, DocumentoContenido, DocumentoPaginas,
    DocumentoKnowledge, CorreoDocumentos, EstadoDocumento,
)

logger = logging.getLogger(__name__)


# ─── Operaciones sobre Documentos ─────────────────────────────────

def crear_documento(
    db: Session,
    titulo_original: str,
    titulo_guardado: str,
    extension: str,
    ruta: str,
    *,
    mime_type: str | None = None,
    tamano_bytes: int | None = None,
    sha256: str | None = None,
) -> Documentos:
    """Crea un nuevo registro de documento en la base de datos.

    Args:
        db: Sesión de base de datos.
        titulo_original: Nombre lógico del documento.
        titulo_guardado: Nombre físico en disco (UUID).
        extension: Extensión del archivo (sin punto).
        ruta: Ruta completa al archivo.
        mime_type: Tipo MIME detectado.
        tamano_bytes: Tamaño del archivo en bytes.
        sha256: Hash SHA256 del archivo.

    Returns:
        Instancia del documento creado.
    """
    documento = Documentos(
        titulo_original=titulo_original,
        titulo_guardado=titulo_guardado,
        tipo=extension,
        extension=extension,
        ruta=ruta,
        mime_type=mime_type,
        tamano_bytes=tamano_bytes,
        sha256=sha256,
        estado=EstadoDocumento.PENDIENTE.value,
        procesado=False,
    )
    db.add(documento)
    db.commit()
    db.refresh(documento)

    logger.info(
        "Documento creado: ID %d, '%s' (%s, %s bytes)",
        documento.id, titulo_original, extension,
        tamano_bytes or "desconocido",
    )
    return documento


def obtener_documento(db: Session, doc_id: int) -> Documentos | None:
    """Obtiene un documento por su ID.

    Args:
        db: Sesión de base de datos.
        doc_id: ID del documento.

    Returns:
        Instancia del documento o None si no existe.
    """
    return db.get(Documentos, doc_id)


def listar_documentos(db: Session) -> list[Documentos]:
    """Lista todos los documentos ordenados por título.

    Args:
        db: Sesión de base de datos.

    Returns:
        Lista de documentos.
    """
    return db.query(Documentos).order_by(Documentos.titulo_original).all()


def actualizar_estado(
    db: Session,
    doc_id: int,
    estado: EstadoDocumento,
    error: str | None = None,
) -> None:
    """Actualiza el estado de procesamiento de un documento.

    Args:
        db: Sesión de base de datos.
        doc_id: ID del documento.
        estado: Nuevo estado.
        error: Mensaje de error (si aplica).
    """
    documento = db.get(Documentos, doc_id)
    if not documento:
        logger.warning("Documento ID %d no encontrado para actualizar estado.", doc_id)
        return

    documento.estado = estado.value
    documento.error_procesamiento = error
    db.commit()

    logger.info("Documento ID %d: estado → %s", doc_id, estado.value)


def marcar_procesado(db: Session, doc_id: int) -> None:
    """Marca un documento como completamente procesado.

    Args:
        db: Sesión de base de datos.
        doc_id: ID del documento.
    """
    documento = db.get(Documentos, doc_id)
    if not documento:
        logger.warning("Documento ID %d no encontrado para marcar procesado.", doc_id)
        return

    documento.procesado = True
    documento.estado = EstadoDocumento.COMPLETADO.value
    documento.error_procesamiento = None
    db.commit()

    logger.info("Documento ID %d marcado como procesado.", doc_id)


# ─── Operaciones sobre Contenido ──────────────────────────────────

def guardar_contenido(
    db: Session,
    doc_id: int,
    texto_completo: str,
    idioma: str | None,
    num_paginas: int,
    parser_utilizado: str,
    hash_contenido: str,
) -> DocumentoContenido:
    """Guarda o actualiza el contenido textual extraído de un documento.

    Args:
        db: Sesión de base de datos.
        doc_id: ID del documento.
        texto_completo: Texto extraído completo.
        idioma: Código ISO del idioma detectado.
        num_paginas: Número de páginas/secciones.
        parser_utilizado: Nombre del parser que extrajo el texto.
        hash_contenido: Hash SHA256 del texto completo.

    Returns:
        Instancia del contenido guardado.
    """
    # Upsert: actualizar si ya existe
    contenido = db.query(DocumentoContenido).filter(
        DocumentoContenido.documento_id == doc_id
    ).first()

    if contenido:
        contenido.texto_completo = texto_completo
        contenido.idioma = idioma
        contenido.num_paginas = num_paginas
        contenido.parser_utilizado = parser_utilizado
        contenido.hash_contenido = hash_contenido
        contenido.fecha_extraccion = datetime.now(timezone.utc)
    else:
        contenido = DocumentoContenido(
            documento_id=doc_id,
            texto_completo=texto_completo,
            idioma=idioma,
            num_paginas=num_paginas,
            parser_utilizado=parser_utilizado,
            hash_contenido=hash_contenido,
        )
        db.add(contenido)

    db.commit()
    db.refresh(contenido)

    logger.info(
        "Contenido guardado para documento ID %d: %d chars, %d páginas, parser='%s'",
        doc_id, len(texto_completo), num_paginas, parser_utilizado,
    )
    return contenido


def guardar_paginas(
    db: Session,
    doc_id: int,
    paginas: list[dict],
) -> None:
    """Guarda las páginas/secciones de un documento.

    Elimina páginas anteriores antes de insertar las nuevas.

    Args:
        db: Sesión de base de datos.
        doc_id: ID del documento.
        paginas: Lista de dicts con: numero_pagina, texto, hash_pagina.
    """
    # Eliminar páginas anteriores
    db.query(DocumentoPaginas).filter(
        DocumentoPaginas.documento_id == doc_id
    ).delete()

    # Insertar nuevas
    for pagina in paginas:
        nueva = DocumentoPaginas(
            documento_id=doc_id,
            numero_pagina=pagina["numero_pagina"],
            texto=pagina["texto"],
            hash_pagina=pagina.get("hash_pagina", ""),
        )
        db.add(nueva)

    db.commit()

    logger.info(
        "Guardadas %d páginas para documento ID %d.", len(paginas), doc_id,
    )


def guardar_conocimiento(
    db: Session,
    doc_id: int,
    resumen: str,
    tipo_documento: str,
    json_llm: dict,
    modelo: str,
    version_prompt: str,
) -> DocumentoKnowledge:
    """Guarda o actualiza el conocimiento generado por IA.

    Args:
        db: Sesión de base de datos.
        doc_id: ID del documento.
        resumen: Resumen del documento.
        tipo_documento: Tipo clasificado (informe, contrato, etc.).
        json_llm: JSON completo del análisis del LLM.
        modelo: Modelo de LLM utilizado.
        version_prompt: Versión del prompt utilizado.

    Returns:
        Instancia del conocimiento guardado.
    """
    # Serializar JSON a string
    json_str = json.dumps(json_llm, ensure_ascii=False, indent=2)

    # Upsert
    knowledge = db.query(DocumentoKnowledge).filter(
        DocumentoKnowledge.documento_id == doc_id
    ).first()

    if knowledge:
        knowledge.resumen = resumen
        knowledge.tipo_documento = tipo_documento
        knowledge.json_llm = json_str
        knowledge.modelo = modelo
        knowledge.version_prompt = version_prompt
        knowledge.fecha_generacion = datetime.now(timezone.utc)
    else:
        knowledge = DocumentoKnowledge(
            documento_id=doc_id,
            resumen=resumen,
            tipo_documento=tipo_documento,
            json_llm=json_str,
            modelo=modelo,
            version_prompt=version_prompt,
        )
        db.add(knowledge)

    db.commit()
    db.refresh(knowledge)

    logger.info(
        "Conocimiento guardado para documento ID %d: tipo='%s', modelo='%s'",
        doc_id, tipo_documento, modelo,
    )
    return knowledge


# ─── Consultas de contenido ───────────────────────────────────────

def obtener_contenido(db: Session, doc_id: int) -> DocumentoContenido | None:
    """Obtiene el contenido textual de un documento.

    Args:
        db: Sesión de base de datos.
        doc_id: ID del documento.

    Returns:
        Contenido o None si no se ha extraído.
    """
    return db.query(DocumentoContenido).filter(
        DocumentoContenido.documento_id == doc_id
    ).first()


def obtener_paginas(db: Session, doc_id: int) -> list[DocumentoPaginas]:
    """Obtiene las páginas de un documento ordenadas.

    Args:
        db: Sesión de base de datos.
        doc_id: ID del documento.

    Returns:
        Lista de páginas ordenadas por número.
    """
    return db.query(DocumentoPaginas).filter(
        DocumentoPaginas.documento_id == doc_id
    ).order_by(DocumentoPaginas.numero_pagina).all()


def obtener_conocimiento(db: Session, doc_id: int) -> DocumentoKnowledge | None:
    """Obtiene el conocimiento generado de un documento.

    Args:
        db: Sesión de base de datos.
        doc_id: ID del documento.

    Returns:
        Conocimiento o None si no se ha generado.
    """
    return db.query(DocumentoKnowledge).filter(
        DocumentoKnowledge.documento_id == doc_id
    ).first()


# ─── Relación Correo ↔ Documento ─────────────────────────────────

def vincular_documento_correo(
    db: Session,
    correo_id: int,
    documento_id: int,
) -> None:
    """Vincula un documento a un correo en la tabla puente.

    Si el vínculo ya existe, no crea duplicado.

    Args:
        db: Sesión de base de datos.
        correo_id: ID del correo.
        documento_id: ID del documento.
    """
    existente = db.query(CorreoDocumentos).filter(
        CorreoDocumentos.correo_id == correo_id,
        CorreoDocumentos.documento_id == documento_id,
    ).first()

    if existente:
        return

    vinculo = CorreoDocumentos(
        correo_id=correo_id,
        documento_id=documento_id,
    )
    db.add(vinculo)
    db.commit()

    logger.debug(
        "Documento ID %d vinculado a correo ID %d.", documento_id, correo_id,
    )


def obtener_documentos_correo(db: Session, correo_id: int) -> list[Documentos]:
    """Obtiene los documentos vinculados a un correo.

    Args:
        db: Sesión de base de datos.
        correo_id: ID del correo.

    Returns:
        Lista de documentos vinculados.
    """
    vinculos = db.query(CorreoDocumentos).filter(
        CorreoDocumentos.correo_id == correo_id
    ).all()

    if not vinculos:
        return []

    doc_ids = [v.documento_id for v in vinculos]
    return db.query(Documentos).filter(Documentos.id.in_(doc_ids)).all()


def obtener_ids_documentos_correo(db: Session, correo_id: int) -> list[int]:
    """Obtiene solo los IDs de documentos vinculados a un correo.

    Args:
        db: Sesión de base de datos.
        correo_id: ID del correo.

    Returns:
        Lista de IDs de documentos.
    """
    vinculos = db.query(CorreoDocumentos).filter(
        CorreoDocumentos.correo_id == correo_id
    ).all()

    return [v.documento_id for v in vinculos]


def documentos_pendientes(db: Session) -> list[Documentos]:
    """Obtiene documentos pendientes de procesamiento o con error.

    Args:
        db: Sesión de base de datos.

    Returns:
        Lista de documentos que necesitan procesamiento.
    """
    return db.query(Documentos).filter(
        Documentos.estado.in_([
            EstadoDocumento.PENDIENTE.value,
            EstadoDocumento.ERROR.value,
        ])
    ).all()
