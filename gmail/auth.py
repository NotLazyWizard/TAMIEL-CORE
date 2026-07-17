"""
gmail/auth.py — Autenticación OAuth2 para Gmail API.

Maneja el flujo de autorización y el almacenamiento del token.
El token se renueva automáticamente cuando expira.
"""

import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config.settings import GMAIL_CREDENTIALS_PATH, GMAIL_TOKEN_PATH

logger = logging.getLogger(__name__)

# Scope necesario para enviar correos
SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def obtener_credenciales() -> Credentials:
    """Obtiene credenciales OAuth2 válidas para Gmail API.
    
    Si existe un token guardado y es válido, lo reutiliza.
    Si el token está expirado, intenta renovarlo con el refresh token.
    Si no hay token, inicia el flujo de autorización.
    
    Returns:
        Credenciales OAuth2 válidas.
    
    Raises:
        FileNotFoundError: Si no existe credentials.json.
        Exception: Si falla el flujo de autorización.
    """
    creds: Credentials | None = None
    token_path = Path(GMAIL_TOKEN_PATH)
    creds_path = Path(GMAIL_CREDENTIALS_PATH)

    # Intentar cargar token existente
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(
            str(token_path), SCOPES
        )
        logger.debug("Token de Gmail cargado desde archivo.")

    # Verificar si las credenciales son válidas
    if creds and creds.valid:
        return creds

    # Intentar refrescar el token
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _guardar_token(creds, token_path)
            logger.info("Token de Gmail renovado correctamente.")
            return creds
        except Exception as e:
            logger.warning("No se pudo renovar el token: %s", e)
            # Continuar al flujo completo de autorización

    # Flujo de autorización completo
    if not creds_path.exists():
        raise FileNotFoundError(
            f"No se encontró credentials.json en: {creds_path}\n"
            "Descárgalo desde Google Cloud Console → APIs → Credentials → OAuth 2.0"
        )

    flow = InstalledAppFlow.from_client_secrets_file(
        str(creds_path), SCOPES
    )
    creds = flow.run_local_server(port=0)
    _guardar_token(creds, token_path)
    logger.info("Autorización de Gmail completada. Token guardado.")

    return creds


def _guardar_token(creds: Credentials, token_path: Path) -> None:
    """Guarda el token de acceso en disco para reutilización."""
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
