"""
ai/transcriptor.py — Agente Transcriptor.

Responsabilidad única: Audio → Texto.
Usa el modelo Whisper disponible en Groq.
No realiza ningún otro procesamiento.
"""

import logging
from pathlib import Path

from ai.groq_client import obtener_cliente
from config.settings import GROQ_MODEL_TRANSCRIPTOR

logger = logging.getLogger(__name__)


def transcribir_audio(ruta_audio: str | Path) -> str:
    """Transcribe un archivo de audio a texto usando Groq (Whisper).
    
    Args:
        ruta_audio: Ruta al archivo de audio (OGG, MP3, WAV, etc.)
    
    Returns:
        Texto transcrito del audio.
    
    Raises:
        FileNotFoundError: Si el archivo de audio no existe.
        Exception: Si hay un error en la API de Groq.
    """
    ruta = Path(ruta_audio)

    if not ruta.exists():
        raise FileNotFoundError(f"Archivo de audio no encontrado: {ruta}")

    logger.info(
        "Transcribiendo audio: %s (modelo: %s)",
        ruta.name, GROQ_MODEL_TRANSCRIPTOR
    )

    cliente = obtener_cliente()

    with open(ruta, "rb") as archivo_audio:
        transcripcion = cliente.audio.transcriptions.create(
            model=GROQ_MODEL_TRANSCRIPTOR,
            file=archivo_audio,
            language="es",
            response_format="text",
        )

    texto = transcripcion.strip() if isinstance(transcripcion, str) else transcripcion.text.strip()
    logger.info("Transcripción completada: %d caracteres.", len(texto))

    return texto
