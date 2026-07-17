"""
config/database.py — Modelos SQLAlchemy y configuración de la base de datos.

Tablas:
    - Correos: Borradores y correos enviados
    - Documentos: Registro de documentos disponibles para adjuntar
    - Destinatarios: Contactos frecuentes
"""

from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    DateTime, Enum as SAEnum, inspect, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
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
    documentos = Column(Text, nullable=True)             # IDs de documentos separados por coma
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


class Documentos(Base):
    """Registro de documentos recibidos y disponibles para adjuntar en correos."""

    __tablename__ = "documentos"

    id              = Column(Integer, primary_key=True, index=True)
    titulo_original = Column(String, nullable=False)    # Nombre lógico del documento
    titulo_guardado = Column(String, nullable=False)    # Nombre físico en disco (UUID)
    tipo            = Column(String, nullable=False)    # Extensión (pdf, docx, etc.)
    ruta            = Column(String, nullable=False)    # Ruta completa en storage/documentos/
    fecha_subida    = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc)
    )


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


# ─── Inicialización y migraciones ─────────────────────────────────

def init_db() -> None:
    """Crea las tablas si no existen y ejecuta migraciones compatibles."""
    Base.metadata.create_all(bind=engine)
    _migrar_corpus_a_cuerpo()
    _agregar_columnas_faltantes()
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
            logger.info(f"Columna '{nombre}' agregada a tabla correos.")


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