FROM python:3.11-slim

# ffmpeg нужен воркеру (шаг assembling) и dev-генерации сырья
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

EXPOSE 8000
# по умолчанию поднимается web; воркер — отдельным сервисом: python -m app.worker.runner
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
