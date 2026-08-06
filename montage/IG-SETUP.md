# Подключение Instagram — сбор статистики Reels

Коллектор `montage/ig_stats.py` тянет статистику твоих Reels из Instagram и
складывает в `reels.json` — панель `platform.systemop.top/reels.html` сразу
показывает вердикт по реальным роликам.

## Что API отдаёт, а что — нет

| Метрика | Откуда |
|---|---|
| Показы / охват, среднее время досмотра | ✅ API |
| Сохранения, репосты, лайки, комменты, дата | ✅ API |
| **Hook 3с, % досмотра до конца, кривая удержания** | ❌ только в приложении |

Недостающее коллектор **оценивает** из среднего досмотра (в панели помечено `~`);
точные цифры со скрина Insights вписываешь руками — оценку они перетрут, не наоборот.

---

## СПОСОБ A — вход через Instagram (по умолчанию, без Facebook-страницы) ⭐️

Самый простой: Facebook-страница и бизнес-портфолио НЕ нужны.

**1. Аккаунт — профессиональный** (Business или Creator). У тебя уже есть.

**2. Создать приложение Meta.**
[developers.facebook.com](https://developers.facebook.com) → *My Apps* → **Create App**
→ на вопрос о назначении выбери **«Other» / «Другое»** → тип **Business** → создать.

**3. Добавить продукт Instagram.**
В приложении слева *Add product* → **Instagram** → кнопка
**«API setup with Instagram login»** (Настройка API со входом через Instagram).

**4. Сгенерировать токен.**
В разделе **«1. Generate access tokens»**:
- **Add account** → войти в свой Instagram → разрешить доступ;
- убедись, что в правах отмечены `instagram_business_basic` и
  **`instagram_business_manage_insights`**;
- нажми **Generate token** → скопируй токен (живёт ~60 дней).

**5. Прописать ключ.**
`montage/.env` (см. `montage/.env.example`), затем `chmod 600 montage/.env`:
```
IG_ACCESS_TOKEN=IGAA...      # токен из шага 4
# IG_USER_ID не нужен в этом режиме
```

**6. Проверить и собрать:**
```bash
python3 montage/ig_stats.py --whoami            # покажет @username
python3 montage/ig_stats.py --limit 25 --write  # запишет в reels.json
```

Продление токена раз в ~50 дней: `python3 montage/ig_stats.py --refresh-token`
(в этом режиме app id/secret не нужны).

---

## СПОСОБ B — через Facebook-страницу (запасной)

Если по какой-то причине нужен классический путь: перевести режим
`IG_AUTH=facebook` в `.env` и задать `IG_USER_ID`, `IG_ACCESS_TOKEN`
(права `instagram_manage_insights`), токен из Graph API Explorer. Требует
привязки Instagram к Facebook-странице. В РФ этот путь часто глючит —
используй способ A.

---

## Дальше — автосбор

Скажи «настрой автосбор» — повешу ежедневный запуск коллектора + авто-продление
токена + автопуш `reels.json` в `main` (панель обновляется сама).
