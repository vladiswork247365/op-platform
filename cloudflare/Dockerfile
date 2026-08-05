# Cloudflare Containers — образ авто-рендера (HTTP-триггер, stateless-цикл).
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://rclone.org/install.sh | bash

WORKDIR /app
COPY montage/ /app/montage/
RUN pip install --no-cache-dir -r /app/montage/requirements.txt \
    && python3 -c "import imageio_ffmpeg; imageio_ffmpeg.get_ffmpeg_exe()"
# субтитры по речи + предзагрузка модели (можно убрать для лёгких/дешёвых рендеров)
RUN pip install --no-cache-dir -r /app/montage/requirements-subs.txt \
    && python3 -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

COPY cloudflare/service.py /app/service.py
ENV PORT=8080 DATA=/data
EXPOSE 8080
CMD ["python3", "/app/service.py"]
