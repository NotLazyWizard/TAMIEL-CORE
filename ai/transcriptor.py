"""
ai/transcriptor.py — Agente Transcriptor.

Responsabilidad única: Audio → Texto.
Usa la interfaz LLMProvider para la transcripción.
No realiza ningún otro procesamiento.
"""

import logging
from pathlib import Path

from ai.groq_provider import obtener_llm_provider
from config.settings import GROQ_MODEL_TRANSCRIPTOR

logger = logging.getLogger(__name__)


def transcribir_audio(ruta_audio: str | Path) -> str:
    """Transcribe un archivo de audio a texto usando el proveedor LLM.

    Args:
        ruta_audio: Ruta al archivo de audio (OGG, MP3, WAV, etc.)

    Returns:
        Texto transcrito del audio.

    Raises:
        FileNotFoundError: Si el archivo de audio no existe.
        Exception: Si hay un error en la API del proveedor.
    """
    ruta = Path(ruta_audio)

    if not ruta.exists():
        raise FileNotFoundError(f"Archivo de audio no encontrado: {ruta}")

    logger.info(
        "Transcribiendo audio: %s (modelo: %s)",
        ruta.name, GROQ_MODEL_TRANSCRIPTOR
    )

    provider = obtener_llm_provider(model_transcriptor=GROQ_MODEL_TRANSCRIPTOR)
    texto = provider.transcribe_audio(ruta, language="es")

    logger.info("Transcripción completada: %d caracteres.", len(texto))
    return texto
