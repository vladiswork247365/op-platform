# Развёртывание на Cloudflare (Containers + Worker)

**Что гоняет рендер:** Cloudflare **Container** (Linux + ffmpeg + whisper) — «станок».
**Что его будит:** Cloudflare **Worker** по крону — «диспетчер». ffmpeg на самих Workers
не работает (нет Linux-бинарников), поэтому монтаж делает именно контейнер.

```
Worker (cron, каждые 5 мин) ──будит──▶ Container (ffmpeg+whisper)
                                          │ rclone: 00 Исходники → рендер → 01 Готовые
                                          ▼ отснятое → в архив (инбокс пустеет)
```

> Требуется: аккаунт Cloudflare с планом **Workers Paid** (Containers — платная бета).
> Проверить деплой из чата нельзя — аккаунт твой. Логика цикла (`service.py`) протестирована.

## Шаги (один раз)

### 1. Получить токен Google для rclone (на своём ноутбуке)
```bash
rclone config      # n → имя gdrive → drive → scope 1 → войти в свой Google
rclone config show gdrive     # скопируй строку token = {...}
```

### 2. (опц.) Завести папку архива «02 Архив» в том же проекте на Диске
Скопируй её ID из адреса — понадобится как `ARCHIVE_ID` (без него инбокс не пустеет
и каждый запуск будет пересобирать всё заново).

### 3. Секреты и деплой
```bash
npm i @cloudflare/containers
npx wrangler secret put RCLONE_CONFIG_GDRIVE_TYPE      # значение: drive
npx wrangler secret put RCLONE_CONFIG_GDRIVE_SCOPE     # значение: drive
npx wrangler secret put RCLONE_CONFIG_GDRIVE_TOKEN     # значение: {...} из шага 1
npx wrangler secret put ARCHIVE_ID                     # ID папки архива (опц.)
npx wrangler deploy
```

`IN_ID` / `OUT_ID` / `REMOTE` уже прописаны в `wrangler.jsonc`.

## Как проверить
- Ручной прогон: открой `https://reels-factory.<твой>.workers.dev/run` — вернёт JSON статуса.
- Дальше крон каждые 5 минут сам собирает новое из «00 Исходники» в «01 Готовые».

## Заметки
- Whisper на CPU тяжёлый: контейнер `standard`. Не нужны субтитры по речи — убери из
  `cloudflare/Dockerfile` строки `requirements-subs.txt` (рендер станет легче и дешевле).
- Тот же движок разворачивается и на VPS (`server/`) — если Containers-бета окажется
  неудобной, площадку меняем без переписывания движка.
