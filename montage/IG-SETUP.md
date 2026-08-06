# Подключение Instagram API — сбор статистики Reels

Коллектор `montage/ig_stats.py` тянет статистику твоих Reels прямо из Instagram
и складывает в `reels.json` — панель на `platform.systemop.top/reels.html`
сразу показывает вердикт по реальным роликам.

## Что API отдаёт, а что — нет

| Метрика | Откуда |
|---|---|
| Показы / охват (views, reach) | ✅ API |
| Среднее время досмотра (avg watch) | ✅ API |
| Сохранения, репосты, лайки, комменты | ✅ API |
| Дата публикации | ✅ API |
| **Hook 3с, % досмотра до конца, кривая удержания** | ❌ API не отдаёт — только в приложении |

Недостающее коллектор **оценивает** из среднего досмотра (в панели помечено `~`).
Точные цифры вписываешь руками со скрина Insights → оценка их не перетирает.

## Разовая настройка (~15 мин)

**1. Перевести аккаунт в профессиональный.**
Instagram → Настройки → «Тип аккаунта» → *Business* или *Creator*.

**2. Привязать к Facebook-странице.**
Нужна любая FB-страница (создаётся бесплатно за минуту).
Instagram → Настройки → «Связанные аккаунты» → привязать страницу.

**3. Создать приложение Meta.**
[developers.facebook.com](https://developers.facebook.com) → *My Apps* → *Create App*
→ тип **Business** → добавить продукт **Instagram Graph API**.
Пока приложение в режиме *Development* — для **своего** аккаунта проверка (App Review)
НЕ нужна: ты как админ/тестер уже можешь читать инсайты.

**4. Получить токен.**
*Tools → Graph API Explorer* → выбрать своё приложение → *Get User Access Token*.
Отметить права:
`instagram_basic`, `instagram_manage_insights`, `pages_show_list`, `pages_read_engagement`.
Нажать *Generate Access Token* → скопировать.

**5. Узнать IG_USER_ID.**
В том же Explorer выполнить:
- `GET /me/accounts` → взять `id` своей страницы;
- `GET /{page-id}?fields=instagram_business_account` → поле
  `instagram_business_account.id` — это и есть **IG_USER_ID**.

**6. Продлить токен до ~60 дней.**
Короткий токен живёт час. Долгий:
`GET /oauth/access_token?grant_type=fb_exchange_token&client_id={app-id}&client_secret={app-secret}&fb_exchange_token={короткий-токен}`
Либо: вписать `IG_APP_ID`, `IG_APP_SECRET`, короткий `IG_ACCESS_TOKEN` в `.env` и
запустить `python3 montage/ig_stats.py --refresh-token`.

## Прописать ключи

`montage/.env` (см. `montage/.env.example`), затем `chmod 600 montage/.env`:

```
IG_USER_ID=17841400000000000
IG_ACCESS_TOKEN=EAAG...
IG_APP_ID=1234567890        # опц. — для продления токена
IG_APP_SECRET=abcd...       # опц.
```

## Запуск

```bash
python3 montage/ig_stats.py --whoami            # проверка: покажет @username
python3 montage/ig_stats.py --limit 25          # показать статы (без записи)
python3 montage/ig_stats.py --limit 25 --write  # записать в reels.json
```

После `--write` открой панель — вердикт по реальным роликам уже там.

## Дальше — автосбор

Токен живёт ~60 дней; сбор можно повесить на ежедневный запуск (cron/Routine) с
авто-продлением токена (`--refresh-token`) раз в ~50 дней. Скажу «настрой автосбор» —
повешу.
