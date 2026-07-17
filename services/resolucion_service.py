"""
services/resolucion_service.py — Resolución de entidades.

Resuelve nombres lógicos a datos concretos:
- Nombres de personas → correos electrónicos (tabla Destinatarios)
- Nombres de documentos → rutas de archivos (tabla Documentos)

Esta lógica la ejecuta Python, NUNCA el LLM.
"""

import logging
from sqlalchemy.orm import Session

from config.database import Destinatarios, Documentos

logger = logging.getLogger(__name__)


# ─── Resultado de resolución ──────────────────────────────────────

class ResultadoResolucion:
    """Resultado de la resolución de una entidad."""

    def __init__(self):
        self.resueltos: list[dict] = []       # Entidades resueltas con éxito
        self.no_encontrados: list[str] = []   # Nombres sin coincidencia
        self.ambiguos: list[dict] = []        # Nombres con múltiples coincidencias


# ─── Resolución de destinatarios ──────────────────────────────────

def resolver_destinatarios(
    nombres: list[str],
    db: Session,
) -> ResultadoResolucion:
    """Resuelve una lista de nombres a correos electrónicos.
    
    Busca en la tabla Destinatarios por coincidencia parcial (case-insensitive).
    Si un nombre tiene múltiples coincidencias, lo marca como ambiguo.
    
    Args:
        nombres: Lista de nombres a resolver.
        db: Sesión de base de datos.
    
    Returns:
        ResultadoResolucion con resueltos, no encontrados y ambiguos.
    """
    resultado = ResultadoResolucion()

    for nombre in nombres:
        nombre_limpio = nombre.strip()
        if not nombre_limpio:
            continue

        # Búsqueda case-insensitive con LIKE
        coincidencias = db.query(Destinatarios).filter(
            Destinatarios.nombre.ilike(f"%{nombre_limpio}%")
        ).all()

        if len(coincidencias) == 0:
            resultado.no_encontrados.append(nombre_limpio)
            logger.warning("Destinatario no encontrado: '%s'", nombre_limpio)

        elif len(coincidencias) == 1:
            dest = coincidencias[0]
            resultado.resueltos.append({
                "nombre": dest.nombre,
                "correo": dest.correo,
                "id": dest.id,
            })
            logger.info(
                "Destinatario resuelto: '%s' → %s",
                nombre_limpio, dest.correo
            )

        else:
            # Múltiples coincidencias → ambiguo
            opciones = [
                {"nombre": d.nombre, "correo": d.correo, "id": d.id}
                for d in coincidencias
            ]
            resultado.ambiguos.append({
                "nombre_buscado": nombre_limpio,
                "opciones": opciones,
            })
            logger.warning(
                "Destinatario ambiguo: '%s' → %d coincidencias",
                nombre_limpio, len(coincidencias)
            )

    return resultado


# ─── Resolución de documentos ─────────────────────────────────────

def resolver_documentos(
    nombres: list[str],
    db: Session,
) -> ResultadoResolucion:
    """Resuelve una lista de nombres lógicos de documentos a rutas de archivos.
    
    Busca en la tabla Documentos por coincidencia parcial (case-insensitive).
    
    Args:
        nombres: Lista de nombres lógicos de documentos.
        db: Sesión de base de datos.
    
    Returns:
        ResultadoResolucion con resueltos, no encontrados y ambiguos.
    """
    resultado = ResultadoResolucion()

    for nombre in nombres:
        nombre_limpio = nombre.strip()
        if not nombre_limpio:
            continue

        coincidencias = db.query(Documentos).filter(
            Documentos.titulo_original.ilike(f"%{nombre_limpio}%")
        ).all()

        if len(coincidencias) == 0:
            resultado.no_encontrados.append(nombre_limpio)
            logger.warning("Documento no encontrado: '%s'", nombre_limpio)

        elif len(coincidencias) == 1:
            doc = coincidencias[0]
            resultado.resueltos.append({
                "titulo": doc.titulo_original,
                "ruta": doc.ruta,
                "tipo": doc.tipo,
                "id": doc.id,
            })
            logger.info(
                "Documento resuelto: '%s' → %s",
                nombre_limpio, doc.ruta
            )

        else:
            opciones = [
                {"titulo": d.titulo_original, "ruta": d.ruta, "tipo": d.tipo, "id": d.id}
                for d in coincidencias
            ]
            resultado.ambiguos.append({
                "nombre_buscado": nombre_limpio,
                "opciones": opciones,
            })
            logger.warning(
                "Documento ambiguo: '%s' → %d coincidencias",
                nombre_limpio, len(coincidencias)
            )

    return resultado


# ─── Formateo para mensajes Telegram ──────────────────────────────

def formatear_problemas_resolucion(
    res_dest: ResultadoResolucion,
    res_docs: ResultadoResolucion,
) -> str | None:
    """Genera un mensaje legible con los problemas de resolución encontrados.
    
    Returns:
        Mensaje formateado o None si no hay problemas.
    """
    lineas: list[str] = []

    if res_dest.no_encontrados:
        lineas.append("❌ *Destinatarios no encontrados:*")
        for nombre in res_dest.no_encontrados:
            lineas.append(f"  • {nombre}")
        lineas.append(
            "\nUsa `/nuevo_destinatario nombre correo` para agregarlos."
        )

    if res_dest.ambiguos:
        lineas.append("\n⚠️ *Destinatarios ambiguos:*")
        for ambiguo in res_dest.ambiguos:
            lineas.append(f"  • \"{ambiguo['nombre_buscado']}\" coincide con:")
            for opcion in ambiguo["opciones"]:
                lineas.append(f"    — {opcion['nombre']} ({opcion['correo']})")

    if res_docs.no_encontrados:
        lineas.append("\n❌ *Documentos no encontrados:*")
        for nombre in res_docs.no_encontrados:
            lineas.append(f"  • {nombre}")
        lineas.append(
            "\nUsa `/añadir_documento titulo tipo` con el archivo adjunto."
        )

    if res_docs.ambiguos:
        lineas.append("\n⚠️ *Documentos ambiguos:*")
        for ambiguo in res_docs.ambiguos:
            lineas.append(f"  • \"{ambiguo['nombre_buscado']}\" coincide con:")
            for opcion in ambiguo["opciones"]:
                lineas.append(f"    — {opcion['titulo']} ({opcion['tipo']})")

    return "\n".join(lineas) if lineas else None
