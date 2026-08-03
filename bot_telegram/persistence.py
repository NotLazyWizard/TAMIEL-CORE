"""
bot_telegram/persistence.py — Persistencia SQLite para el bot de Telegram.

Implementa BasePersistence de python-telegram-bot respaldado por SQLite.
Permite que los estados conversacionales y datos de usuario sobrevivan
reinicios del bot, del contenedor Docker y de la Raspberry Pi.

Almacena:
    - Conversations: estado actual de cada ConversationHandler por usuario.
    - User data: datos temporales del usuario (ej. ruta del archivo temporal).

Reutilizable para cualquier ConversationHandler futuro del proyecto.
"""

import json
import logging
from typing import Any

from telegram.ext import BasePersistence, PersistenceInput
from config.database import SessionLocal, BotPersistencia

logger = logging.getLogger(__name__)


class SQLitePersistence(BasePersistence):
    """Persistencia de estado conversacional en SQLite.

    Utiliza la tabla `bot_persistencia` como almacén clave-valor.
    Solo persiste `user_data` y `conversations` (los únicos necesarios
    para el wizard de documentos y futuros wizards).

    Tipos de registro:
        - tipo='conversation:<nombre>'  → estado del ConversationHandler
        - tipo='user_data'              → datos temporales del usuario
    """

    def __init__(self) -> None:
        super().__init__(
            store_data=PersistenceInput(
                bot_data=False,
                chat_data=False,
                user_data=True,
                callback_data=False,
            ),
        )
        logger.info("SQLitePersistence inicializada.")

    # ─── Helpers de lectura/escritura ──────────────────────────────

    @staticmethod
    def _leer(tipo: str, clave: str) -> dict | None:
        """Lee un valor de la tabla de persistencia.

        Args:
            tipo: Categoría del dato (ej. 'user_data', 'conversation:wizard_documento').
            clave: Clave dentro de esa categoría (ej. user_id como string).

        Returns:
            dict parseado del JSON almacenado, o None si no existe.
        """
        db = SessionLocal()
        try:
            registro = db.query(BotPersistencia).filter(
                BotPersistencia.tipo == tipo,
                BotPersistencia.clave == clave,
            ).first()

            if registro:
                return json.loads(registro.valor)
            return None
        except Exception as e:
            logger.error("Error leyendo persistencia [%s:%s]: %s", tipo, clave, e)
            return None
        finally:
            db.close()

    @staticmethod
    def _escribir(tipo: str, clave: str, valor: Any) -> None:
        """Escribe o actualiza un valor en la tabla de persistencia.

        Args:
            tipo: Categoría del dato.
            clave: Clave dentro de esa categoría.
            valor: Valor serializable a JSON.
        """
        db = SessionLocal()
        try:
            registro = db.query(BotPersistencia).filter(
                BotPersistencia.tipo == tipo,
                BotPersistencia.clave == clave,
            ).first()

            valor_json = json.dumps(valor, ensure_ascii=False, default=str)

            if registro:
                registro.valor = valor_json
            else:
                registro = BotPersistencia(
                    tipo=tipo,
                    clave=clave,
                    valor=valor_json,
                )
                db.add(registro)

            db.commit()
        except Exception as e:
            logger.error("Error escribiendo persistencia [%s:%s]: %s", tipo, clave, e)
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def _eliminar(tipo: str, clave: str) -> None:
        """Elimina un registro de persistencia."""
        db = SessionLocal()
        try:
            db.query(BotPersistencia).filter(
                BotPersistencia.tipo == tipo,
                BotPersistencia.clave == clave,
            ).delete()
            db.commit()
        except Exception as e:
            logger.error("Error eliminando persistencia [%s:%s]: %s", tipo, clave, e)
            db.rollback()
        finally:
            db.close()

    @staticmethod
    def _leer_todos(tipo: str) -> dict:
        """Lee todos los registros de un tipo como diccionario {clave: valor}."""
        db = SessionLocal()
        try:
            registros = db.query(BotPersistencia).filter(
                BotPersistencia.tipo == tipo,
            ).all()

            resultado = {}
            for reg in registros:
                try:
                    resultado[reg.clave] = json.loads(reg.valor)
                except json.JSONDecodeError:
                    logger.warning("JSON inválido en persistencia [%s:%s]", tipo, reg.clave)

            return resultado
        except Exception as e:
            logger.error("Error leyendo todos [%s]: %s", tipo, e)
            return {}
        finally:
            db.close()

    # ─── Conversations (estado de ConversationHandlers) ────────────

    async def get_conversations(self, name: str) -> dict:
        """Carga todos los estados de un ConversationHandler.

        Args:
            name: Nombre del ConversationHandler (ej. 'wizard_documento').

        Returns:
            dict con {key_tuple_serializada: estado_int}.
        """
        tipo = f"conversation:{name}"
        datos_raw = self._leer_todos(tipo)

        # Las claves de ConversationHandler son tuplas (chat_id, user_id).
        # Las almacenamos como string JSON y las restauramos.
        resultado = {}
        for clave_str, estado in datos_raw.items():
            try:
                clave_tuple = tuple(json.loads(clave_str))
                resultado[clave_tuple] = estado
            except (json.JSONDecodeError, TypeError):
                # Intentar como clave simple (int)
                try:
                    resultado[int(clave_str)] = estado
                except ValueError:
                    logger.warning("Clave de conversación inválida: %s", clave_str)

        logger.debug(
            "Conversaciones restauradas para '%s': %d estados.", name, len(resultado),
        )
        return resultado

    async def update_conversation(
        self, name: str, key: tuple, new_state: int | None,
    ) -> None:
        """Actualiza el estado de una conversación.

        Args:
            name: Nombre del ConversationHandler.
            key: Tupla identificadora (chat_id, user_id) o similar.
            new_state: Nuevo estado numérico, o None para eliminar.
        """
        tipo = f"conversation:{name}"
        clave_str = json.dumps(key)

        if new_state is None:
            self._eliminar(tipo, clave_str)
            logger.debug("Conversación eliminada [%s:%s].", name, clave_str)
        else:
            self._escribir(tipo, clave_str, new_state)
            logger.debug(
                "Conversación actualizada [%s:%s] → estado %d.", name, clave_str, new_state,
            )

    # ─── User data (datos temporales del usuario) ──────────────────

    async def get_user_data(self) -> dict[int, dict]:
        """Carga todos los user_data almacenados.

        Returns:
            dict con {user_id: datos_dict}.
        """
        datos_raw = self._leer_todos("user_data")

        resultado = {}
        for clave_str, datos in datos_raw.items():
            try:
                user_id = int(clave_str)
                resultado[user_id] = datos if isinstance(datos, dict) else {}
            except ValueError:
                logger.warning("user_id inválido en persistencia: %s", clave_str)

        logger.debug("User data restaurado: %d usuarios.", len(resultado))
        return resultado

    async def update_user_data(self, user_id: int, data: dict) -> None:
        """Persiste los datos de un usuario."""
        self._escribir("user_data", str(user_id), data)

    async def refresh_user_data(self, user_id: int, user_data: dict) -> dict:
        """Refresca user_data desde la base de datos."""
        datos = self._leer("user_data", str(user_id))
        if datos and isinstance(datos, dict):
            return datos
        return user_data

    async def drop_user_data(self, user_id: int) -> None:
        """Elimina los datos persistidos de un usuario."""
        self._eliminar("user_data", str(user_id))
        logger.debug("User data eliminado para user_id %d.", user_id)

    # ─── Bot data (no utilizado, stubs requeridos) ─────────────────

    async def get_bot_data(self) -> dict:
        return {}

    async def update_bot_data(self, data: dict) -> None:
        pass

    async def refresh_bot_data(self, bot_data: dict) -> dict:
        return bot_data

    # ─── Chat data (no utilizado, stubs requeridos) ────────────────

    async def get_chat_data(self) -> dict[int, dict]:
        return {}

    async def update_chat_data(self, chat_id: int, data: dict) -> None:
        pass

    async def refresh_chat_data(self, chat_id: int, chat_data: dict) -> dict:
        return chat_data

    async def drop_chat_data(self, chat_id: int) -> None:
        pass

    # ─── Callback data (no utilizado, stubs requeridos) ────────────

    async def get_callback_data(self):
        return None

    async def update_callback_data(self, data) -> None:
        pass

    # ─── Flush ─────────────────────────────────────────────────────

    async def flush(self) -> None:
        """No-op: cada escritura ya hace commit inmediato."""
        logger.debug("SQLitePersistence flush (no-op, escritura síncrona).")
