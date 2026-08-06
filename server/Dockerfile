# Reels-фабрика — авто-обработчик для всегда-онлайн сервера.
# Забирает исходники из Google Drive (rclone), рендерит вертикальный ролик
# движком montage/, кладёт результат обратно в Drive. Крутится 24/7.
FROM python:3.11-slim

# ffmpeg идёт статикой в imageio-ffmpeg (ставится из requirements),
# нужны только шрифты (кириллица для субтитров), rclone и базовые утилиты.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core curl unzip ca-certificates libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# rclone — синхронизация с Google Drive
RUN curl -fsSL https://rclone.org/install.sh | bash

WORKDIR /app
COPY montage/ /app/montage/
RUN pip install --no-cache-dir -r /app/montage/requirements.txt \
    && python3 -c "import imageio_ffmpeg; print('ffmpeg:', imageio_ffmpeg.get_ffmpeg_exe())"

# субтитры по речи + предзагрузка модели в образ (чтобы рантайм был offline-быстрым)
RUN pip install --no-cache-dir -r /app/montage/requirements-subs.txt \
    && python3 -c "from faster_whisper import WhisperModel; WhisperModel('small', device='cpu', compute_type='int8')"

# про-арсенал виральности: auto-editor (динамика) + librosa (биты музыки)
RUN pip install --no-cache-dir -r /app/montage/requirements-pro.txt

COPY server/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# /data — рабочие sources/out; /config/rclone — конфиг rclone (том с хоста)
VOLUME ["/data", "/config"]
ENV RCLONE_CONFIG=/config/rclone.conf
ENTRYPOINT ["/app/entrypoint.sh"]
