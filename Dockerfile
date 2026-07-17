# ── Etapa de build ──────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Instalar dependencias del sistema mínimas
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Etapa de producción ────────────────────────────────────
FROM python:3.12-slim

WORKDIR /app

# Copiar dependencias instaladas
COPY --from=builder /install /usr/local

# Copiar código fuente
COPY . .

# Crear directorios necesarios
RUN mkdir -p data storage/documentos

# Usuario no-root para seguridad
RUN useradd --create-home appuser && \
    chown -R appuser:appuser /app
USER appuser

# Punto de entrada
CMD ["python", "main.py"]
