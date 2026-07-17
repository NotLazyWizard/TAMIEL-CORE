"""
ai/groq_client.py — Cliente Groq reutilizable (singleton).

Centraliza la conexión a Groq para evitar crear múltiples instancias.
"""

import logging
from groq import Groq
from config.settings import GROQ_API_KEY

logger = logging.getLogger(__name__)

_cliente: Groq | None = None


def obtener_cliente() -> Groq:
    """Retorna una instancia singleton del cliente Groq.
    
    Returns:
        Instancia de Groq configurada con la API key.
    
    Raises:
        ValueError: Si GROQ_API_KEY no está configurada.
    """
    global _cliente

    if _cliente is None:
        if not GROQ_API_KEY:
            raise ValueError(
                "GROQ_API_KEY no está configurada. "
                "Revisa tu archivo .env"
            )
        _cliente = Groq(api_key=GROQ_API_KEY)
        logger.info("Cliente Groq inicializado correctamente.")

    return _cliente
