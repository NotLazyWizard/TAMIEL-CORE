"""
config/settings.py — Carga centralizada de configuración.

Todas las variables de entorno se validan y centralizan aquí.
Los módulos importan desde este archivo en lugar de llamar a os.getenv directamente.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Cargar variables de entorno desde .env
load_dotenv()

logger = logging.getLogger(__name__)

# ─── Rutas del proyecto ───────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STORAGE_DIR = BASE_DIR / "storage"
DOCUMENTOS_DIR = STORAGE_DIR / "documentos"

# Crear directorios necesarios si no existen
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCUMENTOS_DIR.mkdir(parents=True, exist_ok=True)

# ─── Base de datos ────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'usuario.db'}")

# ─── Groq API ─────────────────────────────────────────────────────
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL_TRANSCRIPTOR: str = os.getenv("GROQ_MODEL_TRANSCRIPTOR", "whisper-large-v3")
GROQ_MODEL_REDACTOR: str = os.getenv("GROQ_MODEL_REDACTOR", "meta-llama/llama-4-scout-17b-16e-instruct")

# ─── Telegram ─────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_ADMIN_CHAT_ID: int = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "0"))

# ─── Gmail OAuth2 ─────────────────────────────────────────────────
GMAIL_CREDENTIALS_PATH: str = os.getenv(
    "GMAIL_CREDENTIALS_PATH",
    str(DATA_DIR / "credentials.json")
)
GMAIL_TOKEN_PATH: str = os.getenv(
    "GMAIL_TOKEN_PATH",
    str(DATA_DIR / "token.json")
)
GMAIL_REMITENTE: str = os.getenv("GMAIL_REMITENTE", "")

# ─── Configuración general ────────────────────────────────────────
MAX_REWRITE_ATTEMPTS: int = int(os.getenv("MAX_REWRITE_ATTEMPTS", "5"))
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ─── Tipos de archivo soportados ──────────────────────────────────
EXTENSIONES_PERMITIDAS: set[str] = {
    "pdf", "docx", "xlsx", "pptx", "txt",
    "png", "jpg", "jpeg",
}

# ─── Validación ───────────────────────────────────────────────────

def validar_configuracion() -> list[str]:
    """Valida que las variables de entorno críticas estén configuradas.
    
    Returns:
        Lista de advertencias. Si está vacía, todo está correcto.
    """
    advertencias: list[str] = []

    if not GROQ_API_KEY or GROQ_API_KEY == "PON_AQUI_TU_GROQ_API_KEY":
        advertencias.append("⚠️ GROQ_API_KEY no está configurada.")

    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "PON_AQUI_TU_TOKEN_DE_TELEGRAM":
        advertencias.append("⚠️ TELEGRAM_BOT_TOKEN no está configurado.")

    if TELEGRAM_ADMIN_CHAT_ID == 0:
        advertencias.append("⚠️ TELEGRAM_ADMIN_CHAT_ID no está configurado.")

    if not GMAIL_REMITENTE:
        advertencias.append("⚠️ GMAIL_REMITENTE no está configurado.")

    if not Path(GMAIL_CREDENTIALS_PATH).exists():
        advertencias.append(
            f"⚠️ No se encontró credentials.json en {GMAIL_CREDENTIALS_PATH}. "
            "Gmail API no funcionará hasta que se configure."
        )

    for adv in advertencias:
        logger.warning(adv)

    return advertencias
