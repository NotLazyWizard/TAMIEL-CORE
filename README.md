# 🤖 Tamiel — Asistente Inteligente de Correos por Telegram

Sistema multiagente ligero que permite **redactar y enviar correos electrónicos profesionales mediante notas de voz en Telegram**. Diseñado para ejecutarse en una Raspberry Pi 5 con Docker.

Envías una nota de voz, el sistema la transcribe, redacta un correo profesional, te lo muestra para revisión, y al aprobar lo envía por Gmail automáticamente.

---

## 📋 Tabla de Contenidos

- [Arquitectura](#-arquitectura)
- [Flujo de Trabajo](#-flujo-de-trabajo)
- [Requisitos Previos](#-requisitos-previos)
- [Instalación](#-instalación)
- [Configuración](#-configuración)
- [Uso del Bot](#-uso-del-bot)
- [Estructura del Proyecto](#-estructura-del-proyecto)
- [Mantenimiento](#-mantenimiento)
- [Resolución de Problemas](#-resolución-de-problemas)

---

## 🏗 Arquitectura

Tamiel **no es simplemente un bot de Telegram**. Es un sistema multiagente donde Telegram actúa únicamente como interfaz de usuario. Toda la inteligencia artificial se ejecuta mediante APIs externas (Groq), manteniendo el consumo de recursos al mínimo.

```
┌──────────────────────────────────────────────────────────┐
│                     USUARIO                              │
│                  (Telegram App)                          │
└─────────────────────┬────────────────────────────────────┘
                      │ Nota de voz
                      ▼
┌──────────────────────────────────────────────────────────┐
│               BOT DE TELEGRAM                            │
│            (bot_telegram/)                               │
│  • Recibe audio          • Muestra borradores            │
│  • Registra comandos     • Gestiona aprobaciones         │
└─────────┬───────────────────────────────┬────────────────┘
          │                               │
          ▼                               ▼
┌──────────────────┐           ┌───────────────────────┐
│  🎙 TRANSCRIPTOR │           │    📋 SERVICIOS       │
│    (ai/)         │           │    (services/)        │
│  Groq / Whisper  │           │ • Resolución nombres  │
│  Audio → Texto   │           │ • Gestión de estados  │
└────────┬─────────┘           │ • Orquestación        │
         │                     └───────────┬───────────┘
         ▼                                 │
┌──────────────────┐                       │
│  ✍️ REDACTOR     │                       │
│    (ai/)         │                       │
│  Groq / LLM     │                       │
│  Texto → JSON    │                       │
└────────┬─────────┘                       │
         │                                 │
         ▼                                 ▼
┌──────────────────┐           ┌───────────────────────┐
│  🗄 BASE DATOS   │           │    📧 GMAIL API       │
│  (SQLite)        │           │    (gmail/)           │
│  • Correos       │           │  OAuth2 + MIME        │
│  • Destinatarios │           │  Envío autenticado    │
│  • Documentos    │           └───────────────────────┘
└──────────────────┘
```

### Principios de diseño

| Principio | Implementación |
|---|---|
| **IA solo por API** | Groq para transcripción (Whisper) y redacción (LLM). Sin modelos locales. |
| **Resolución por Python** | Nombres → emails y documentos → rutas los resuelve Python, nunca el LLM. |
| **Ligero** | SQLite, sin Redis/Celery/Kafka. ~512 MB RAM máximo. |
| **Modular** | Cada módulo tiene responsabilidad única. Sin archivos >300 líneas. |
| **Seguro** | Gmail con OAuth2, no SMTP con contraseña. Bot restringido a un admin. |

---

## 🔄 Flujo de Trabajo

### Flujo principal (nota de voz → correo enviado)

```
1. 🎙  Envías una nota de voz por Telegram
       "Manda un correo a Carlos diciéndole que el reporte está listo"

2. 📝  El Transcriptor convierte el audio a texto (Groq/Whisper)
       → "Manda un correo a Carlos diciéndole que el reporte está listo"

3. ✍️  El Redactor genera un JSON estructurado (Groq/LLM)
       → { "destinatarios": ["Carlos"], "asunto": "...", "cuerpo": "...", "adjuntos": [] }

4. 🔍  Python resuelve las entidades
       → "Carlos" → carlos@empresa.com  (tabla Destinatarios)
       → "Reporte Mensual" → storage/documentos/abc123.pdf  (tabla Documentos)

5. 📋  Recibes el borrador para revisión con opciones:
       ✅ /enviar_ID     — Enviar tal cual
       📝 /feedback_ID   — Solicitar cambios
       ❌ /cancelar_ID   — Descartar

6. 📝  (Opcional) Envías feedback, el LLM re-redacta y repites hasta aprobar

7. 📧  Al aprobar, Python construye el MIME y envía vía Gmail API con OAuth2
```

### Ciclo de vida de un correo (estados)

```
NOTA_RECIBIDA → REDACTANDO → ESPERANDO_APROBACION → ENVIANDO → ENVIADO
                     ↑               │
                     └── feedback ───┘
                                     │
                              CANCELADO (desde cualquier estado activo)
```

---

## 📦 Requisitos Previos

- **Python 3.12+**
- **Docker y Docker Compose** (para despliegue en producción)
- **Cuenta de Groq** con API key → [console.groq.com](https://console.groq.com)
- **Bot de Telegram** creado con [@BotFather](https://t.me/BotFather)
- **Proyecto de Google Cloud** con Gmail API habilitada y credenciales OAuth2

---

## 🚀 Instalación

### Opción A: Ejecución local (desarrollo)

```bash
# 1. Clonar el repositorio
git clone <tu-repositorio>
cd RedactorAutomataCorreos

# 2. Crear entorno virtual
python -m venv .venv
source .venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Edita .env con tus credenciales (ver sección Configuración)

# 5. Colocar credentials.json de Google OAuth2 en data/
mkdir -p data
cp /ruta/a/tu/credentials.json data/

# 6. Ejecutar (la primera vez abrirá el navegador para autorizar Gmail)
python main.py
```

### Opción B: Docker (producción / Raspberry Pi)

```bash
# 1. Configurar .env
cp .env.example .env
# Edita .env con tus credenciales

# 2. Colocar credentials.json
mkdir -p data
cp /ruta/a/tu/credentials.json data/

# 3. IMPORTANTE: Primera ejecución local para autorizar Gmail
#    (necesitas un navegador para el flujo OAuth2)
python main.py
#    Una vez autorizado, se genera data/token.json → Ctrl+C

# 4. Construir y ejecutar con Docker
docker compose up -d --build

# Ver logs
docker compose logs -f bot
```

> **Nota para Raspberry Pi:** La imagen usa `python:3.12-slim` que es compatible con ARM64. El límite de memoria está configurado en 512 MB.

---

## ⚙️ Configuración

### Variables de entorno (`.env`)

| Variable | Descripción | Ejemplo |
|---|---|---|
| `GROQ_API_KEY` | API key de Groq | `gsk_abc123...` |
| `GROQ_MODEL_TRANSCRIPTOR` | Modelo de transcripción | `whisper-large-v3` |
| `GROQ_MODEL_REDACTOR` | Modelo de redacción | `meta-llama/llama-4-scout-17b-16e-instruct` |
| `TELEGRAM_BOT_TOKEN` | Token del bot de Telegram | `123456:ABC-DEF...` |
| `TELEGRAM_ADMIN_CHAT_ID` | Tu chat ID de Telegram | `987654321` |
| `GMAIL_CREDENTIALS_PATH` | Ruta a credentials.json | `data/credentials.json` |
| `GMAIL_TOKEN_PATH` | Ruta al token OAuth2 (auto-generado) | `data/token.json` |
| `GMAIL_REMITENTE` | Tu correo de Gmail | `tu@gmail.com` |
| `DATABASE_URL` | URL de la base de datos SQLite | `sqlite:///data/usuario.db` |
| `MAX_REWRITE_ATTEMPTS` | Máximo de iteraciones con feedback | `5` |
| `LOG_LEVEL` | Nivel de logging | `INFO` |

### Modelos de Groq intercambiables

Puedes cambiar los modelos editando `.env` sin tocar el código:

**Transcripción (audio → texto):**
| Modelo | Velocidad | Calidad |
|---|---|---|
| `whisper-large-v3` | Rápido | Alta (recomendado) |
| `whisper-large-v3-turbo` | Muy rápido | Media-Alta |
| `distil-whisper-large-v3-en` | Muy rápido | Media (solo inglés) |

**Redacción (texto → JSON):**
| Modelo | Tokens/min | Calidad |
|---|---|---|
| `meta-llama/llama-4-scout-17b-16e-instruct` | Alto | Muy alta (recomendado) |
| `llama-3.3-70b-versatile` | Medio | Muy alta |
| `gemma2-9b-it` | Alto | Alta |

> Consulta los modelos disponibles en [console.groq.com/docs/models](https://console.groq.com/docs/models)

### Gmail API (OAuth2)

1. Ve a [Google Cloud Console](https://console.cloud.google.com)
2. Crea un proyecto (o usa uno existente)
3. Habilita **Gmail API** en "APIs y Servicios"
4. Ve a **Credenciales** → **Crear credenciales** → **ID de cliente OAuth 2.0**
5. Tipo de aplicación: **Aplicación de escritorio**
6. Descarga el JSON y guárdalo como `data/credentials.json`
7. En la primera ejecución, se abrirá el navegador para autorizar acceso

---

## 💬 Uso del Bot

### Enviar un correo (flujo principal)

Simplemente **envía una nota de voz** al bot describiendo el correo. Ejemplo:

> 🎙 *"Manda un correo a Carlos diciéndole que la reunión de mañana se pospone para el jueves a las 3"*

El bot responderá con:
1. La transcripción del audio
2. El borrador del correo con opciones para aprobar, editar o cancelar

### Comandos disponibles

#### 📧 Correos
| Comando | Descripción |
|---|---|
| *(nota de voz)* | Inicia el flujo de redacción de correo |
| `/estado_correos` | Lista todos los correos activos con su estado |
| `/correo_ID` | Ver el detalle completo de un correo (ej: `/correo_3`) |
| `/enviar_ID` | Aprobar y enviar un correo (ej: `/enviar_3`) |
| `/feedback_ID mensaje` | Solicitar cambios (ej: `/feedback_3 Hazlo más formal`) |
| `/cancelar_ID` | Cancelar un correo (ej: `/cancelar_3`) |

#### 👤 Destinatarios
| Comando | Descripción |
|---|---|
| `/destinatarios` | Ver todos los contactos guardados |
| `/nuevo_destinatario nombre correo` | Agregar contacto (ej: `/nuevo_destinatario Carlos Pérez carlos@empresa.com`) |

#### 📎 Documentos
| Comando | Descripción |
|---|---|
| `/documentos` | Ver todos los documentos disponibles |
| `/documento_ID` | Descargar un documento (ej: `/documento_5`) |
| `/añadir_documento título` | Subir documento con el archivo adjunto como caption |

#### ⚙️ Sistema
| Comando | Descripción |
|---|---|
| `/start` | Ver menú de ayuda |
| `/tokens` | Verificar cuota disponible de Groq |
| `/flujo` | Ver el diagrama del flujo del sistema |

### Ejemplo de `/feedback`

```
Tú:     /feedback_3 Cambia el saludo a "Estimado Ingeniero" y agrega 
        que se adjunta el acta de la reunión anterior

Tamiel: 📝 Feedback recibido. Re-redactando correo ID 3...
        [Muestra el nuevo borrador con los cambios aplicados]
```

Puedes iterar con feedback hasta un máximo de 5 veces (configurable con `MAX_REWRITE_ATTEMPTS`).

### Subir un documento

Para que el bot pueda adjuntar documentos en correos, primero debes subirlos:

1. Adjunta el archivo (PDF, DOCX, XLSX, etc.) al chat del bot
2. Escribe como **caption** del archivo: `/añadir_documento Nombre Lógico`
3. Después, al dictar una nota de voz puedes decir: *"adjunta el Nombre Lógico"*

**Formatos soportados:** PDF, DOCX, XLSX, PPTX, TXT, PNG, JPG, JPEG

---

## 📂 Estructura del Proyecto

```
RedactorAutomataCorreos/
│
├── main.py                     # Punto de entrada: logging, DB, bot
│
├── config/                     # Configuración
│   ├── settings.py             # Variables de entorno centralizadas
│   └── database.py             # Modelos SQLAlchemy + migraciones
│
├── ai/                         # Agentes de IA (solo APIs, sin modelos locales)
│   ├── groq_client.py          # Cliente Groq singleton
│   ├── transcriptor.py         # Audio → Texto (Whisper)
│   └── redactor.py             # Texto → JSON (LLM)
│
├── bot_telegram/               # Interfaz de Telegram
│   ├── bot.py                  # Creación de app y registro de handlers
│   ├── handlers_comandos.py    # /start, /tokens, /flujo, /estado_correos
│   ├── handlers_correo.py      # Notas de voz, /feedback, /enviar, /cancelar
│   ├── handlers_destinatarios.py  # /destinatarios, /nuevo_destinatario
│   └── handlers_documentos.py  # /documentos, /documento_ID, /añadir_documento
│
├── services/                   # Lógica de negocio
│   ├── correo_service.py       # Orquestador del pipeline completo
│   ├── resolucion_service.py   # Nombres → emails / documentos → rutas
│   └── estado_service.py       # Máquina de estados con validación
│
├── gmail/                      # Envío de correos
│   ├── auth.py                 # OAuth2 con refresh automático
│   └── sender.py               # Constructor MIME + Gmail API
│
├── utils/                      # Funciones auxiliares
│   ├── helpers.py              # Escapar markdown, extraer IDs
│   └── generador_txt.py        # Genera previews .txt de correos
│
├── data/                       # Datos persistentes (gitignored)
│   ├── usuario.db              # Base de datos SQLite
│   ├── credentials.json        # Credenciales Google OAuth2
│   └── token.json              # Token de acceso Gmail (auto-generado)
│
├── storage/
│   └── documentos/             # Archivos adjuntos subidos por el usuario
│
├── requirements.txt            # Dependencias Python
├── Dockerfile                  # Imagen Docker multi-stage
├── docker-compose.yml          # Orquestación con volúmenes persistentes
├── .env.example                # Template de configuración
└── .gitignore
```

### ¿Por qué `bot_telegram/` y no `telegram/`?

El paquete `python-telegram-bot` se importa como `import telegram`. Si el directorio local se llama `telegram/`, Python lo resuelve primero y rompe todos los imports de la librería. Por eso se llama `bot_telegram/`.

---

## 🔧 Mantenimiento

### Base de datos

La base de datos SQLite se almacena en `data/usuario.db`. Las migraciones son **aditivas y automáticas**: al iniciar, el sistema verifica si faltan columnas y las agrega sin perder datos.

```bash
# Ver la base de datos manualmente
sqlite3 data/usuario.db

# Tablas disponibles
.tables
# → correos  destinatarios  documentos

# Ver esquema
.schema correos

# Consultas útiles
SELECT id, asunto, estado, fecha_creacion FROM correos ORDER BY id DESC LIMIT 10;
SELECT nombre, correo FROM destinatarios;
SELECT titulo_original, tipo, ruta FROM documentos;
```

### Logs

El nivel de log se configura con `LOG_LEVEL` en `.env`:

| Nivel | Qué muestra |
|---|---|
| `DEBUG` | Todo, incluyendo respuestas del LLM |
| `INFO` | Operaciones normales (recomendado) |
| `WARNING` | Solo advertencias y errores |
| `ERROR` | Solo errores |

```bash
# Ver logs en Docker
docker compose logs -f bot

# Logs con timestamp
docker compose logs -f --timestamps bot
```

### Actualizar modelos de IA

Simplemente edita `.env` y reinicia:

```bash
# Editar
nano .env
# Cambiar GROQ_MODEL_REDACTOR=nuevo-modelo

# Reiniciar
docker compose restart bot
```

### Actualizar dependencias

```bash
# Editar requirements.txt si es necesario
pip install -r requirements.txt --upgrade

# Reconstruir imagen Docker
docker compose up -d --build
```

### Renovar token de Gmail

El token se renueva automáticamente. Si expira completamente (e.g., revocaste el acceso):

```bash
# Eliminar token viejo
rm data/token.json

# Ejecutar localmente para re-autorizar (necesitas navegador)
python main.py
# Autoriza en el navegador → Ctrl+C → Vuelve a Docker
docker compose up -d
```

### Backups

```bash
# Backup de base de datos y documentos
cp data/usuario.db data/usuario.db.bak
tar czf backup_documentos.tar.gz storage/documentos/
```

### Gestión de documentos

Los documentos se almacenan en `storage/documentos/` con nombres UUID para evitar colisiones. La correspondencia nombre lógico ↔ archivo físico está en la tabla `documentos` de SQLite.

Para eliminar un documento:
```sql
-- Primero obtén la ruta
SELECT id, titulo_original, ruta FROM documentos WHERE titulo_original LIKE '%reporte%';

-- Elimina el registro (luego borra el archivo manualmente)
DELETE FROM documentos WHERE id = X;
```
```bash
rm storage/documentos/uuid-del-archivo.pdf
```

---

## 🐛 Resolución de Problemas

### El bot no responde

1. Verifica que `TELEGRAM_BOT_TOKEN` sea correcto
2. Verifica que `TELEGRAM_ADMIN_CHAT_ID` sea tu chat ID real (usa [@userinfobot](https://t.me/userinfobot))
3. Revisa los logs: `docker compose logs bot`

### "GROQ_API_KEY no está configurada"

Verifica que tu `.env` tenga la API key válida de [console.groq.com/keys](https://console.groq.com/keys).

### "Rate limit exceeded" al transcribir/redactar

Groq tiene límites en su plan gratuito. Usa `/tokens` para verificar cuota. Espera el tiempo indicado o considera un plan de pago.

### "No se encontró credentials.json"

Descarga el archivo OAuth2 desde Google Cloud Console y colócalo en `data/credentials.json`. Ver la sección [Gmail API (OAuth2)](#gmail-api-oauth2).

### "Destinatario no encontrado"

El LLM usa nombres lógicos. Si dice "Carlos" pero no existe en la tabla:
```
/nuevo_destinatario Carlos Pérez carlos@empresa.com
```

### El correo no se envía

1. Verifica que `GMAIL_REMITENTE` sea el correo que autorizaste con OAuth2
2. Verifica que `data/token.json` exista y no esté corrupto
3. Revisa que los destinatarios estén resueltos (el correo necesita `destinatarios_email`)

### Error de memoria en Raspberry Pi

El `docker-compose.yml` limita la memoria a 512 MB. Si necesitas más:
```yaml
deploy:
  resources:
    limits:
      memory: 768M  # Aumentar aquí
```

---

## 📄 Licencia

Proyecto privado. Todos los derechos reservados.
