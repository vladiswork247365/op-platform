# Сервер авто-обработки Reels (24/7)

Всегда-онлайн обработчик: телефон льёт исходники в Google Drive «00 Исходники» →
сервер сам их забирает (rclone), рендерит вертикальный ролик движком `montage/` →
кладёт готовое в «01 Готовые» → синхронизируется обратно на телефон.

**ID папок Диска** (уже прописаны в примерах):
- `00 Исходники (съёмки)` → `IN_ID=1QuNqWxBNxhrhvetf13cJLoTQLLHTLbGw`
- `01 Готовые ролики` → `OUT_ID=1PlwYzMJG0CYJxz-0Dkfn9Lrp4K2Ntomc`

---

## Что делаешь только ты (один раз)

1. **Взять VPS.** Любой Ubuntu-сервер (Hetzner / DigitalOcean / Timeweb, ~$4–6/мес).
2. **Авторизовать rclone в свой Google** — интерактивный вход в твой аккаунт,
   за тебя из чата это сделать нельзя (это доступ к твоему Диску).

Всё остальное — код ниже, разворачивается двумя командами.

---

## Вариант 1 — Docker (рекомендую)

```bash
# на VPS, из корня репозитория
docker build -f server/Dockerfile -t reels-factory .

# один раз авторизовать Google Drive (создать remote с именем gdrive):
docker run -it --rm -v reels_cfg:/config -e RCLONE_CONFIG=/config/rclone.conf \
    reels-factory rclone config
#   n → gdrive → drive → scope 1 → (headless: rclone authorize "drive" на ноутбуке)

# запуск 24/7
docker run -d --name reels --restart unless-stopped \
    -v reels_cfg:/config -v reels_data:/data \
    -e IN_ID=1QuNqWxBNxhrhvetf13cJLoTQLLHTLbGw \
    -e OUT_ID=1PlwYzMJG0CYJxz-0Dkfn9Lrp4K2Ntomc \
    -e INTERVAL=60 \
    reels-factory

docker logs -f reels        # смотреть, как забирает и рендерит
```

## Вариант 2 — без Docker (systemd)

```bash
bash server/setup-vps.sh          # ставит зависимости, показывает rclone config
# после rclone config создать сервис:
sudo tee /etc/systemd/system/reels.service >/dev/null <<'UNIT'
[Unit]
Description=Reels factory auto-render
After=network-online.target
[Service]
WorkingDirectory=/root/op-platform
Environment=IN_ID=1QuNqWxBNxhrhvetf13cJLoTQLLHTLbGw
Environment=OUT_ID=1PlwYzMJG0CYJxz-0Dkfn9Lrp4K2Ntomc
Environment=INTERVAL=60
ExecStart=/usr/bin/env bash server/entrypoint.sh
Restart=always
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl enable --now reels
journalctl -u reels -f
```

---

## Как это ведёт себя

- Новый файл в «00 Исходники» → в пределах `INTERVAL` секунд собирается черновой
  динамичный ролик из всего, что в папке (нарезка, панчи, Ken Burns, музыка, хук
  из имени файла) → появляется в «01 Готовые».
- Дедуп: пока набор файлов не менялся — повторно не рендерит.
- **Совет по workflow:** после сборки перенеси отснятое из «00 Исходники» в архивную
  подпапку, чтобы следующий ролик собирался из новой партии, а не из всего сразу.

## Что можно улучшить дальше

- Точные субтитры по смыслу речи — модуль транскрибации (whisper) поверх движка.
- Telegram-уведомление «ролик готов» — n8n-нода на событие в «01 Готовые».
- Финальный AI-рендер (клон голоса, AI-вставки) — Higgsfield при наличии кредитов.

> Если дашь мне доступ к серверу (SSH) — разверну и настрою всё сам, останется
> только один раз пройти rclone-авторизацию в твой Google.
