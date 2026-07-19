"""
config/database.py — Modelos SQLAlchemy y configuración de la base de datos.

Tablas:
    - Correos: Borradores y correos enviados
    - Documentos: Registro de documentos disponibles para adjuntar
    - Destinatarios: Contactos frecuentes
    - DocumentoContenido: Texto extraído de documentos
    - DocumentoPaginas: Texto por páginas/secciones
    - DocumentoKnowledge: Conocimiento generado por IA
    - CorreoDocumentos: Tabla puente correo ↔ documento
"""

from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    DateTime, Boolean, ForeignKey, Enum as SAEnum, inspect, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from datetime import datetime, timezone
from contextlib import contextmanager
import enum
import logging

from config.settings import DATABASE_URL

logger = logging.getLogger(__name__)

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


# ─── Enums ────────────────────────────────────────────────────────

class EstadoCorreo(str, enum.Enum):
    """Estados posibles de un correo en el sistema."""
    NOTA_RECIBIDA        = "Nota Recibida"          # Nota de voz recibida, procesando audio
    REDACTANDO           = "Redactando"              # LLM redactando el correo
    ESPERANDO_APROBACION = "Esperando Aprobación"    # Esperando revisión del usuario
    ENVIANDO             = "Enviando"                # Correo en proceso de envío
    ENVIADO              = "Enviado"                 # Correo enviado exitosamente
    CANCELADO            = "Cancelado"               # Correo cancelado por el usuario


class EstadoDocumento(str, enum.Enum):
    """Estados del procesamiento de un documento."""
    PENDIENTE   = "pendiente"       # Archivo guardado, sin procesar
    PROCESANDO  = "procesando"      # Extracción de contenido en curso
    COMPLETADO  = "completado"      # Procesamiento exitoso
    ERROR       = "error"           # Error en el procesamiento


# ─── Modelos ──────────────────────────────────────────────────────

class Correos(Base):
    """Registro de correos: desde nota de voz hasta envío."""

    __tablename__ = "correos"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, nullable=False)
    texto_transcrito = Column(Text, nullable=True)
    destinatarios = Column(String, nullable=True)       # Nombres resueltos separados por coma
    destinatarios_email = Column(String, nullable=True)  # Emails resueltos separados por coma
    asunto = Column(String, nullable=True)
    cuerpo = Column(Text, nullable=True)                # Antes: corpus
    documentos = Column(Text, nullable=True)             # IDs de documentos separados por coma (legacy)
    estado = Column(
        SAEnum(EstadoCorreo),
        default=EstadoCorreo.NOTA_RECIBIDA
    )
    fecha_creacion = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )
    fecha_envio = Column(DateTime, nullable=True)
    feedback_usuario = Column(Text, nullable=True)
    intentos_redaccion = Column(Integer, default=0)

    # --- Relación con tabla puente ---
    adjuntos_rel = relationship("CorreoDocumentos", back_populates="correo")


class Documentos(Base):
    """Registro de documentos recibidos y disponibles para adjuntar en correos."""

    __tablename__ = "documentos"

    # --- Columnas originales (compatibilidad) ---
    id              = Column(Integer, primary_key=True, index=True)
    titulo_original = Column(String, nullable=False)    # Nombre lógico del documento
    titulo_guardado = Column(String, nullable=False)    # Nombre físico en disco (UUID)
    tipo            = Column(String, nullable=False)    # Extensión (pdf, docx, etc.)
    ruta            = Column(String, nullable=False)    # Ruta completa en storage/documentos/
    fecha_subida    = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )

    # --- Columnas nuevas (metadatos extendidos) ---
    extension           = Column(String, nullable=True)
    mime_type           = Column(String, nullable=True)
    tamano_bytes        = Column(Integer, nullable=True)
    sha256              = Column(String(64), nullable=True)
    procesado           = Column(Boolean, default=False)
    estado              = Column(String, default=EstadoDocumento.PENDIENTE.value)
    error_procesamiento = Column(Text, nullable=True)

    # --- Relaciones ---
    contenido    = relationship(
        "DocumentoContenido", back_populates="documento",
        uselist=False, cascade="all, delete-orphan",
    )
    paginas      = relationship(
        "DocumentoPaginas", back_populates="documento",
        cascade="all, delete-orphan", order_by="DocumentoPaginas.numero_pagina",
    )
    conocimiento = relationship(
        "DocumentoKnowledge", back_populates="documento",
        uselist=False, cascade="all, delete-orphan",
    )
    correos_rel  = relationship("CorreoDocumentos", back_populates="documento")


class Destinatarios(Base):
    """Registro de destinatarios frecuentes (nombre → correo)."""

    __tablename__ = "destinatarios"

    id              = Column(Integer, primary_key=True, index=True)
    nombre          = Column(String, nullable=False)    # Nombre del destinatario
    correo          = Column(String, nullable=False)    # Correo electrónico
    fecha_agregado  = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )


# ─── Modelos documentales nuevos ─────────────────────────────────

class DocumentoContenido(Base):
    """Contenido textual extraído de un documento."""

    __tablename__ = "documento_contenido"

    id               = Column(Integer, primary_key=True, index=True)
    documento_id     = Column(Integer, ForeignKey("documentos.id"), unique=True, nullable=False)
    texto_completo   = Column(Text, nullable=False)
    idioma           = Column(String(10), nullable=True)
    num_paginas      = Column(Integer, nullable=True)
    parser_utilizado = Column(String, nullable=True)
    fecha_extraccion = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    hash_contenido   = Column(String(64), nullable=True)

    documento = relationship("Documentos", back_populates="contenido")


class DocumentoPaginas(Base):
    """Texto dividido por páginas/secciones para futuras búsquedas semánticas."""

    __tablename__ = "documento_paginas"

    id            = Column(Integer, primary_key=True, index=True)
    documento_id  = Column(Integer, ForeignKey("documentos.id"), nullable=False)
    numero_pagina = Column(Integer, nullable=False)
    texto         = Column(Text, nullable=False)
    hash_pagina   = Column(String(64), nullable=True)

    documento = relationship("Documentos", back_populates="paginas")


class DocumentoKnowledge(Base):
    """Conocimiento estructurado generado por IA a partir del documento."""

    __tablename__ = "documento_knowledge"

    id               = Column(Integer, primary_key=True, index=True)
    documento_id     = Column(Integer, ForeignKey("documentos.id"), unique=True, nullable=False)
    resumen          = Column(Text, nullable=True)
    tipo_documento   = Column(String, nullable=True)
    json_llm         = Column(Text, nullable=True)      # JSON completo del LLM
    modelo           = Column(String, nullable=True)
    version_prompt   = Column(String, nullable=True)
    fecha_generacion = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    documento = relationship("Documentos", back_populates="conocimiento")


class CorreoDocumentos(Base):
    """Tabla puente: relación muchos-a-muchos entre correos y documentos."""

    __tablename__ = "correo_documentos"

    id           = Column(Integer, primary_key=True, index=True)
    correo_id    = Column(Integer, ForeignKey("correos.id"), nullable=False)
    documento_id = Column(Integer, ForeignKey("documentos.id"), nullable=False)

    correo    = relationship("Correos", back_populates="adjuntos_rel")
    documento = relationship("Documentos", back_populates="correos_rel")


# ─── Inicialización y migraciones ─────────────────────────────────

def init_db() -> None:
    """Crea las tablas si no existen y ejecuta migraciones compatibles."""
    Base.metadata.create_all(bind=engine)
    _migrar_corpus_a_cuerpo()
    _agregar_columnas_faltantes()
    _agregar_columnas_documentos()
    _migrar_correo_documentos()
    logger.info("Base de datos inicializada correctamente.")


def _migrar_corpus_a_cuerpo() -> None:
    """Migración compatible: copia datos de 'corpus' a 'cuerpo' si existe la columna antigua."""
    inspector = inspect(engine)
    columnas = [col["name"] for col in inspector.get_columns("correos")]

    if "corpus" in columnas and "cuerpo" in columnas:
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE correos SET cuerpo = corpus WHERE cuerpo IS NULL AND corpus IS NOT NULL"
            ))
        logger.info("Migración corpus → cuerpo completada.")
    elif "corpus" in columnas and "cuerpo" not in columnas:
        # SQLite no soporta ALTER COLUMN RENAME directamente en versiones antiguas.
        # Pero desde SQLite 3.25.0 (2018) sí lo soporta.
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE correos RENAME COLUMN corpus TO cuerpo"))
        logger.info("Columna 'corpus' renombrada a 'cuerpo'.")


def _agregar_columnas_faltantes() -> None:
    """Agrega columnas nuevas si no existen (migraciones aditivas)."""
    inspector = inspect(engine)
    columnas_existentes = {col["name"] for col in inspector.get_columns("correos")}

    columnas_nuevas = {
        "destinatarios_email": "VARCHAR",
        "intentos_redaccion": "INTEGER DEFAULT 0",
        "cuerpo": "TEXT",
    }

    for nombre, tipo in columnas_nuevas.items():
        if nombre not in columnas_existentes:
            with engine.begin() as conn:
                conn.execute(text(
                    f"ALTER TABLE correos ADD COLUMN {nombre} {tipo}"
                ))
            logger.info("Columna '%s' agregada a tabla correos.", nombre)


def _agregar_columnas_documentos() -> None:
    """Agrega columnas nuevas a la tabla documentos si no existen."""
    inspector = inspect(engine)

    if "documentos" not in inspector.get_table_names():
        return

    columnas_existentes = {col["name"] for col in inspector.get_columns("documentos")}

    columnas_nuevas = {
        "extension": "VARCHAR",
        "mime_type": "VARCHAR",
        "tamano_bytes": "INTEGER",
        "sha256": "VARCHAR(64)",
        "procesado": "BOOLEAN DEFAULT 0",
        "estado": "VARCHAR DEFAULT 'pendiente'",
        "error_procesamiento": "TEXT",
    }

    for nombre, tipo in columnas_nuevas.items():
        if nombre not in columnas_existentes:
            with engine.begin() as conn:
                conn.execute(text(
                    f"ALTER TABLE documentos ADD COLUMN {nombre} {tipo}"
                ))
            logger.info("Columna '%s' agregada a tabla documentos.", nombre)


def _migrar_correo_documentos() -> None:
    """Migra los IDs de documentos de la columna string a la tabla puente."""
    inspector = inspect(engine)

    if "correo_documentos" not in inspector.get_table_names():
        return

    with engine.begin() as conn:
        # Verificar si ya hay datos migrados
        resultado = conn.execute(text("SELECT COUNT(*) FROM correo_documentos"))
        if resultado.scalar() > 0:
            return  # Ya migrado

        # Obtener correos con documentos en formato string
        correos = conn.execute(text(
            "SELECT id, documentos FROM correos WHERE documentos IS NOT NULL AND documentos != ''"
        )).fetchall()

        migrados = 0
        for correo_id, docs_str in correos:
            for doc_id_str in docs_str.split(","):
                doc_id_str = doc_id_str.strip()
                if doc_id_str.isdigit():
                    conn.execute(text(
                        "INSERT OR IGNORE INTO correo_documentos (correo_id, documento_id) "
                        "VALUES (:c, :d)"
                    ), {"c": correo_id, "d": int(doc_id_str)})
                    migrados += 1

        if migrados > 0:
            logger.info("Migrados %d vínculos correo-documento a tabla puente.", migrados)


# ─── Sesiones ─────────────────────────────────────────────────────

@contextmanager
def get_db():
    """Context manager para obtener una sesión de base de datos.

    Ejemplo:
        with get_db() as db:
            correos = db.query(Correos).all()
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()