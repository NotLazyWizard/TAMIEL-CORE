"""
services/estado_service.py — Gestión de estados de correos.

Controla las transiciones válidas entre estados
y registra cambios con logging.
"""

import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from config.database import Correos, EstadoCorreo

logger = logging.getLogger(__name__)

# Transiciones válidas: estado_actual → [estados_permitidos]
TRANSICIONES_VALIDAS: dict[EstadoCorreo, list[EstadoCorreo]] = {
    EstadoCorreo.NOTA_RECIBIDA: [
        EstadoCorreo.REDACTANDO,
        EstadoCorreo.CANCELADO,
    ],
    EstadoCorreo.REDACTANDO: [
        EstadoCorreo.ESPERANDO_APROBACION,
        EstadoCorreo.CANCELADO,
    ],
    EstadoCorreo.ESPERANDO_APROBACION: [
        EstadoCorreo.REDACTANDO,      # Feedback → re-redacción
        EstadoCorreo.ENVIANDO,         # Aprobado
        EstadoCorreo.CANCELADO,
    ],
    EstadoCorreo.ENVIANDO: [
        EstadoCorreo.ENVIADO,
        EstadoCorreo.ESPERANDO_APROBACION,  # Si falla el envío, vuelve a aprobación
        EstadoCorreo.CANCELADO,
    ],
    EstadoCorreo.ENVIADO: [],          # Estado final
    EstadoCorreo.CANCELADO: [],        # Estado final
}


def transicionar_estado(
    correo: Correos,
    nuevo_estado: EstadoCorreo,
    db: Session,
) -> bool:
    """Cambia el estado de un correo validando la transición.
    
    Args:
        correo: Instancia del correo a modificar.
        nuevo_estado: Estado destino.
        db: Sesión de base de datos.
    
    Returns:
        True si la transición fue exitosa, False si no es válida.
    """
    estado_actual = correo.estado
    estados_permitidos = TRANSICIONES_VALIDAS.get(estado_actual, [])

    if nuevo_estado not in estados_permitidos:
        logger.warning(
            "Transición inválida para correo ID %d: %s → %s. "
            "Transiciones permitidas: %s",
            correo.id,
            estado_actual.value,
            nuevo_estado.value,
            [e.value for e in estados_permitidos],
        )
        return False

    estado_anterior = estado_actual.value
    correo.estado = nuevo_estado

    # Registrar fecha de envío si corresponde
    if nuevo_estado == EstadoCorreo.ENVIADO:
        correo.fecha_envio = datetime.now(timezone.utc)

    db.commit()

    logger.info(
        "Correo ID %d: %s → %s",
        correo.id, estado_anterior, nuevo_estado.value,
    )
    return True
