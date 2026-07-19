"""
services/document_service.py — Gestión de archivos físicos.

Responsabilidad única:
    - Guardar archivos en disco
    - Calcular metadatos físicos (SHA256, MIME type, tamaño)
    - Eliminar archivos

Nunca interpreta contenido.
Nunca utiliza IA.
Nunca accede directamente a la base de datos (delega al repository).
"""

import hashlib
import logging
import mimetypes
import uuid
from pathlib import Path

from config.settings import DOCUMENTOS_DIR

logger = logging.getLogger(__name__)


def calcular_sha256(ruta: Path) -> str:
    """Calcula el hash SHA256 de un archivo.

    Args:
        ruta: Ruta al archivo.

    Returns:
        Hash SHA256 como string hexadecimal.
    """
    sha256 = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(8192), b""):
            sha256.update(bloque)
    return sha256.hexdigest()


def detectar_mime_type(ruta: Path) -> str:
    """Detecta el tipo MIME de un archivo.

    Intenta usar python-magic si está disponible, sino usa mimetypes.

    Args:
        ruta: Ruta al archivo.

    Returns:
        Tipo MIME detectado (ej: 'application/pdf').
    """
    try:
        import magic
        mime = magic.from_file(str(ruta), mime=True)
        if mime:
            return mime
    except (ImportError, Exception) as e:
        logger.debug("python-magic no disponible, usando mimetypes: %s", e)

    mime_type, _ = mimetypes.guess_type(str(ruta))
    return mime_type or "application/octet-stream"


def obtener_tamano(ruta: Path) -> int:
    """Obtiene el tamaño de un archivo en bytes.

    Args:
        ruta: Ruta al archivo.

    Returns:
        Tamaño en bytes.
    """
    return ruta.stat().st_size


def generar_nombre_guardado(extension: str) -> str:
    """Genera un nombre único para almacenar un archivo.

    Args:
        extension: Extensión del archivo (sin punto).

    Returns:
        Nombre de archivo con UUID (ej: 'a1b2c3d4-...-.pdf').
    """
    return f"{uuid.uuid4()}.{extension}"


def guardar_archivo_en_disco(
    contenido_bytes: bytes,
    extension: str,
) -> tuple[Path, str]:
    """Guarda bytes en disco con un nombre único.

    Args:
        contenido_bytes: Contenido del archivo.
        extension: Extensión del archivo (sin punto).

    Returns:
        Tupla (ruta_completa, nombre_guardado).
    """
    DOCUMENTOS_DIR.mkdir(parents=True, exist_ok=True)
    nombre_guardado = generar_nombre_guardado(extension)
    ruta = DOCUMENTOS_DIR / nombre_guardado

    with open(ruta, "wb") as f:
        f.write(contenido_bytes)

    logger.info("Archivo guardado en disco: %s (%d bytes)", ruta, len(contenido_bytes))
    return ruta, nombre_guardado


def eliminar_archivo_de_disco(ruta: str | Path) -> bool:
    """Elimina un archivo físico del disco.

    Args:
        ruta: Ruta al archivo a eliminar.

    Returns:
        True si se eliminó correctamente, False si no se encontró.
    """
    ruta_path = Path(ruta)

    if not ruta_path.exists():
        logger.warning("Archivo no encontrado para eliminar: %s", ruta)
        return False

    try:
        ruta_path.unlink()
        logger.info("Archivo eliminado: %s", ruta)
        return True
    except OSError as e:
        logger.error("Error eliminando archivo %s: %s", ruta, e)
        return False


def obtener_metadatos_archivo(ruta: Path) -> dict:
    """Calcula todos los metadatos físicos de un archivo.

    Args:
        ruta: Ruta al archivo.

    Returns:
        Diccionario con: sha256, mime_type, tamano_bytes, extension.
    """
    extension = ruta.suffix.lstrip(".").lower()

    return {
        "sha256": calcular_sha256(ruta),
        "mime_type": detectar_mime_type(ruta),
        "tamano_bytes": obtener_tamano(ruta),
        "extension": extension,
    }
