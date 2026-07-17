"""
main.py — Punto de entrada del sistema multiagente de correos.

Inicializa: logging, base de datos, validación de config, bot de Telegram.
"""

import logging
import sys

from config.settings import LOG_LEVEL, validar_configuracion
from config.database import init_db
from bot_telegram.bot import crear_aplicacion


def _configurar_logging() -> None:
    """Configura el sistema de logging con formato consistente."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Reducir verbosidad de librerías externas
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)


def main() -> None:
    """Punto de entrada principal del sistema."""
    _configurar_logging()
    logger = logging.getLogger(__name__)

    logger.info("=" * 50)
    logger.info("  Tamiel — Asistente de Correos")
    logger.info("=" * 50)

    # Validar configuración
    advertencias = validar_configuracion()
    if advertencias:
        logger.warning(
            "El sistema iniciará con %d advertencia(s) de configuración.",
            len(advertencias),
        )

    # Inicializar base de datos
    init_db()

    # Crear y ejecutar bot
    logger.info("Iniciando bot de Telegram...")
    app = crear_aplicacion()
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()