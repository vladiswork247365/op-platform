#!/bin/bash
# СБОР СТАТИСТИКИ INSTAGRAM REELS — запуск двойным кликом.
# Тянет статистику твоих Reels из Instagram и обновляет reels.json + панель.
# Токен спросит один раз и сохранит в montage/.env (в git не попадает).
cd "$(dirname "$0")/.."
REPO="$(pwd)"
clear
echo "▶ Сбор статистики Reels из Instagram"
echo "  проект: $REPO"
echo

# 0) python3 обязателен (сам движок — на стандартной библиотеке, ничего ставить не надо)
if ! command -v python3 >/dev/null 2>&1; then
  echo "✗ Не найден python3."
  echo "  В приложении «Терминал» выполни:  xcode-select --install"
  echo "  дождись установки и запусти этот файл снова."
  read -n1 -r -p "Нажми любую клавишу…"; exit 1
fi

# 1) подтянуть свежую версию проекта (если это git-клон)
if [ -d .git ]; then
  echo "▶ Обновляю проект…"
  git pull --ff-only 2>/dev/null || echo "  (не удалось обновить — продолжаю с текущей версией)"
  echo
fi

# 2) токен
ENV="montage/.env"
NEEDTOK=1
if [ -f "$ENV" ] && grep -q '^IG_ACCESS_TOKEN=IGA' "$ENV" 2>/dev/null; then
  read -r -p "▶ Найден сохранённый токен. Использовать его? [Enter — да / n — новый] " ans
  [ "$ans" != "n" ] && NEEDTOK=0
fi
if [ "$NEEDTOK" = "1" ]; then
  echo "▶ Вставь токен Instagram (начинается на IGAA…). Ввод скрыт — вставь и нажми Enter:"
  read -rs TOK; echo
  if [ -z "$TOK" ]; then echo "✗ Пусто — останавливаюсь."; read -n1 -r -p "…"; exit 1; fi
  mkdir -p montage
  [ -f "$ENV" ] && { grep -v '^IG_ACCESS_TOKEN=' "$ENV" > "$ENV.tmp" 2>/dev/null || true; mv "$ENV.tmp" "$ENV" 2>/dev/null || true; }
  echo "IG_ACCESS_TOKEN=$TOK" >> "$ENV"
  chmod 600 "$ENV"
  echo "  токен сохранён в $ENV (в git не попадёт)"
fi
echo

# 3) проверка токена
echo "▶ Проверяю токен…"
if ! python3 montage/ig_stats.py --whoami; then
  echo
  echo "✗ Токен не принят (возможно истёк). Сгенерируй заново в кабинете приложения"
  echo "  и запусти этот файл снова, выбрав «новый токен»."
  read -n1 -r -p "…"; exit 1
fi
echo

# 4) сбор статистики → в reels.json
echo "▶ Собираю статистику последних роликов…"
echo "──────────────────────────────────────────────────────────────────────"
python3 montage/ig_stats.py --limit 25 --write
echo "──────────────────────────────────────────────────────────────────────"
echo

# 5) отправить в панель (или подсказать переслать таблицу)
SENT=0
if [ -d .git ]; then
  echo "▶ Отправляю в панель…"
  git add reels.json 2>/dev/null || true
  if git commit -m "reels: обновление статистики из Instagram" >/dev/null 2>&1; then
    if GIT_TERMINAL_PROMPT=0 git push origin main >/dev/null 2>&1 || GIT_TERMINAL_PROMPT=0 git push >/dev/null 2>&1; then
      SENT=1
      echo "✅ Готово! Панель обновится за 1–2 мин:"
      echo "   https://platform.systemop.top/reels.html"
    fi
  else
    echo "  (новых данных нет — статистика не изменилась)"
    SENT=1
  fi
fi
if [ "$SENT" = "0" ]; then
  echo "ℹ️ Автопуш с этого мака недоступен — ничего страшного."
  echo "   Данные собраны. Пришли Владу в чат ТАБЛИЦУ выше (скрин) — обновлю панель сам."
fi
echo
read -n1 -r -p "Готово. Нажми любую клавишу, чтобы закрыть окно…"
