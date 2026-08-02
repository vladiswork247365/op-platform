# Конвейер: детали

## state.json

```json
{
  "episode": "ep014",
  "date": "2026-08-02",
  "title": "День 14: первый платящий клиент",
  "steps": {
    "ingest": "done",
    "bible": "done",
    "script": "done",
    "edit": "in_progress",
    "motion": "skip",
    "voice": "skip",
    "enhance": "todo",
    "subtitles": "todo",
    "publish": "todo"
  },
  "artifacts": {
    "cut": "work/ep014_cut.mp4",
    "final": null
  }
}
```

Значения шага: `todo` | `in_progress` | `done` | `skip`.
`skip` — осознанно пропущен (например, ролик без озвучки). Не переспрашивай про `skip`.

## Наименование файлов

`ep{NNN}_{шаг}.mp4`, шаги в порядке применения:

| Суффикс | Кто делает |
|---|---|
| `_cut` | video-edit — черновая сборка |
| `_broll` | video-motion — со вставленным генеративным b-roll |
| `_voice` | video-voice — со сведённой озвучкой и музыкой |
| `_up` | video-enhance — апскейл/цвет/резкость |
| `_subs` | video-subtitles — вжатые субтитры |
| `_final` | video-publish — финал под площадку |

Финал кладётся в `out/`, всё остальное — в `work/`.

## Инварианты

1. **Субтитры — последними.** После любого ресайза/апскейла текст теряет резкость.
2. **Звук сводится до апскейла видео.** Апскейл перекодирует контейнер, звук должен быть финальным.
3. **Исходники неприкосновенны.** `raw/` — только чтение.
4. **Один эпизод = одна папка.** Никаких файлов эпизода вне его папки.

## Быстрая инициализация дня

```bash
DAY=$(date +%F); N=$(printf "ep%03d" $(( $(ls content/episodes 2>/dev/null | wc -l) + 1 )))
mkdir -p "content/episodes/${DAY}-${N}"/{raw,notes,work,out}
```

## Если пользователь снял на телефон и скинул в облако

Higgsfield-инструмент `media_upload_widget` даёт виджет загрузки, `media_import_url` — импорт
по ссылке. Google Drive MCP (`search_files` → `download_file_content`) — если материал там.
Локальные файлы всегда предпочтительнее: монтаж через ffmpeg бесплатен, генеративные шаги — нет.
