"""
ai/groq_provider.py — Implementación concreta de LLMProvider para Groq.

Envuelve el cliente Groq existente (groq_client.py) implementando
la interfaz abstracta LLMProvider. El singleton del cliente Groq
se mantiene sin cambios.
"""

import json
import logging
import re
from pathlib import Path

from ai.groq_client import obtener_cliente
from ai.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


class GroqLLMProvider(LLMProvider):
    """Implementación de LLMProvider usando la API de Groq.

    Args:
        model: Modelo para completions de chat.
        model_transcriptor: Modelo para transcripción de audio.
    """

    def __init__(self, model: str, model_transcriptor: str = "whisper-large-v3"):
        self.model = model
        self.model_transcriptor = model_transcriptor
        self._cliente = obtener_cliente()
        logger.info(
            "GroqLLMProvider inicializado (chat: %s, audio: %s)",
            model, model_transcriptor,
        )

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> str:
        """Genera texto usando Groq chat completions."""
        mensajes = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.debug("Enviando a Groq (modelo: %s, tokens: %d)...", self.model, max_tokens)

        respuesta = self._cliente.chat.completions.create(
            model=self.model,
            messages=mensajes,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        contenido = respuesta.choices[0].message.content.strip()
        logger.debug("Respuesta recibida: %d caracteres.", len(contenido))
        return contenido

    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> dict:
        """Genera JSON estructurado usando Groq chat completions."""
        contenido = self.generate_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return _parsear_json(contenido)

    def transcribe_audio(
        self,
        ruta_audio: Path,
        *,
        language: str = "es",
    ) -> str:
        """Transcribe audio usando Groq (Whisper)."""
        ruta = Path(ruta_audio)

        if not ruta.exists():
            raise FileNotFoundError(f"Archivo de audio no encontrado: {ruta}")

        logger.info(
            "Transcribiendo audio: %s (modelo: %s)",
            ruta.name, self.model_transcriptor,
        )

        with open(ruta, "rb") as archivo_audio:
            transcripcion = self._cliente.audio.transcriptions.create(
                model=self.model_transcriptor,
                file=archivo_audio,
                language=language,
                response_format="text",
            )

        texto = (
            transcripcion.strip()
            if isinstance(transcripcion, str)
            else transcripcion.text.strip()
        )

        logger.info("Transcripción completada: %d caracteres.", len(texto))
        return texto

    def verify(self) -> bool:
        """Verifica que Groq esté operativo con una petición mínima."""
        try:
            self._cliente.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "hola"}],
                max_tokens=5,
            )
            return True
        except Exception as e:
            logger.warning("Verificación de Groq fallida: %s", e)
            return False

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Groq no soporta embeddings nativamente."""
        raise NotImplementedError(
            "Embedding no disponible en Groq. "
            "Utilice un proveedor de embeddings dedicado (OpenAI, Cohere, etc.)."
        )


# ─── Parsing de JSON ──────────────────────────────────────────────

def _parsear_json(contenido: str) -> dict:
    """Extrae y parsea JSON de la respuesta del LLM.

    Intenta múltiples estrategias:
    1. Parseo directo
    2. Extracción de bloques markdown
    3. Búsqueda del primer { ... } válido

    Args:
        contenido: Texto de respuesta del LLM.

    Returns:
        Diccionario parseado.

    Raises:
        ValueError: Si no se puede extraer JSON válido.
    """
    # Intento 1: parseo directo
    try:
        return json.loads(contenido)
    except json.JSONDecodeError:
        pass

    # Intento 2: bloques markdown
    patron_md = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", contenido, re.DOTALL)
    if patron_md:
        try:
            return json.loads(patron_md.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Intento 3: primer { ... } válido
    patron_llaves = re.search(r"\{.*\}", contenido, re.DOTALL)
    if patron_llaves:
        try:
            return json.loads(patron_llaves.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"No se pudo extraer JSON válido de la respuesta: {contenido[:300]}"
    )


# ─── Factory / Singleton ──────────────────────────────────────────

_instancia: GroqLLMProvider | None = None


def obtener_llm_provider(
    model: str | None = None,
    model_transcriptor: str | None = None,
) -> GroqLLMProvider:
    """Retorna una instancia singleton del proveedor Groq.

    Args:
        model: Modelo para chat completions (default: GROQ_MODEL_REDACTOR).
        model_transcriptor: Modelo para audio (default: GROQ_MODEL_TRANSCRIPTOR).

    Returns:
        Instancia de GroqLLMProvider.
    """
    global _instancia

    if _instancia is None:
        from config.settings import GROQ_MODEL_REDACTOR, GROQ_MODEL_TRANSCRIPTOR

        _instancia = GroqLLMProvider(
            model=model or GROQ_MODEL_REDACTOR,
            model_transcriptor=model_transcriptor or GROQ_MODEL_TRANSCRIPTOR,
        )

    return _instancia
