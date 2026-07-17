"""
utils/helpers.py — Funciones auxiliares reutilizables.

Funciones comunes usadas en múltiples módulos.
"""

import re


def escapar_markdown(text: str) -> str:
    """Escapa caracteres especiales de Markdown v1 para Telegram.
    
    Args:
        text: Texto a escapar.
    
    Returns:
        Texto con caracteres especiales escapados.
    """
    if not text:
        return text

    caracteres_especiales = ["_", "*", "`", "["]
    for char in caracteres_especiales:
        text = text.replace(char, f"\\{char}")
    return text


def extraer_id(texto: str, prefijo: str) -> int | None:
    """Extrae un ID numérico de un comando de Telegram.
    
    Args:
        texto: Texto completo del comando (e.g., "/cancelar_42").
        prefijo: Prefijo del comando (e.g., "/cancelar_").
    
    Returns:
        ID numérico extraído, o None si no es válido.
    """
    try:
        return int(texto.replace(prefijo, "").split()[0].strip())
    except (ValueError, IndexError):
        return None


def extraer_id_y_texto(texto: str, prefijo: str) -> tuple[int | None, str | None]:
    """Extrae ID y texto restante de un comando (e.g., /feedback_42 mi mensaje).
    
    Args:
        texto: Texto completo del comando.
        prefijo: Prefijo del comando con underscore (e.g., "/feedback_").
    
    Returns:
        Tupla (id, texto_restante). Ambos pueden ser None.
    """
    match = re.match(
        rf"{re.escape(prefijo)}(\d+)\s*(.*)",
        texto,
        re.DOTALL,
    )
    if not match:
        return None, None

    try:
        id_valor = int(match.group(1))
        texto_restante = match.group(2).strip() or None
        return id_valor, texto_restante
    except ValueError:
        return None, None
