"""
ai/llm_provider.py — Interfaz abstracta para proveedores de LLM.

Define las operaciones comunes que cualquier proveedor de IA debe implementar.
Permite cambiar de proveedor (Groq, OpenAI, Anthropic, etc.)
sin modificar la lógica de negocio.
"""

from abc import ABC, abstractmethod
from pathlib import Path


class LLMProvider(ABC):
    """Interfaz abstracta para proveedores de modelos de lenguaje.

    Cualquier proveedor concreto debe implementar los métodos abstractos.
    El método embed() tiene una implementación por defecto que lanza
    NotImplementedError, preparado para futura integración con bases vectoriales.
    """

    @abstractmethod
    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> str:
        """Genera texto a partir de un prompt del sistema y del usuario.

        Args:
            system_prompt: Instrucciones del sistema para el LLM.
            user_prompt: Mensaje del usuario.
            temperature: Creatividad de la respuesta (0.0 - 1.0).
            max_tokens: Máximo de tokens a generar.

        Returns:
            Texto generado por el LLM.
        """

    @abstractmethod
    def generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 4000,
    ) -> dict:
        """Genera JSON estructurado a partir de un prompt.

        Args:
            system_prompt: Instrucciones del sistema (deben pedir JSON).
            user_prompt: Mensaje del usuario.
            temperature: Creatividad de la respuesta.
            max_tokens: Máximo de tokens a generar.

        Returns:
            Diccionario parseado del JSON generado.

        Raises:
            ValueError: Si el LLM no devuelve JSON válido.
        """

    @abstractmethod
    def transcribe_audio(
        self,
        ruta_audio: Path,
        *,
        language: str = "es",
    ) -> str:
        """Transcribe un archivo de audio a texto.

        Args:
            ruta_audio: Ruta al archivo de audio.
            language: Código ISO del idioma (default: español).

        Returns:
            Texto transcrito del audio.
        """

    @abstractmethod
    def verify(self) -> bool:
        """Verifica que el proveedor esté operativo y con cuota disponible.

        Returns:
            True si el proveedor responde correctamente.
        """

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Genera embeddings para una lista de textos.

        Preparado para futura implementación con bases vectoriales.
        Los proveedores que soporten embeddings deben sobreescribir este método.

        Args:
            texts: Lista de textos a convertir en embeddings.

        Returns:
            Lista de vectores (embeddings).

        Raises:
            NotImplementedError: Si el proveedor no soporta embeddings.
        """
        raise NotImplementedError(
            "Embedding no disponible en este proveedor. "
            "Implemente un proveedor de embeddings para esta funcionalidad."
        )
