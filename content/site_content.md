# Наполнение сайта (снимок 2026-10-19T14:17:54Z)


## https://systemop.pro

RU
KK
СИСТЕМА ОП

Вход в панель управления

ЛОГИН
ПАРОЛЬ
Войти


## https://systemop.top

СИСТЕМА ОП
НАЖМИТЕ НА НУЖНЫЙ ОБЪЕКТ
ОТДЕЛ
ПРОДАЖ
ЭКОСИСТЕМА ОП
ОТДЕЛ
ПРОДАЖ
×
ПАНЕЛЬ ДЛЯ РОСТА ВЫРУЧКИ
ПЕРЕЙТИ
УСИЛЕНИЕ ОТДЕЛОВ ПРОДАЖ
ПЕРЕЙТИ
ЭКСПРЕСС-АУДИТ ОТДЕЛА ПРОДАЖ
ПЕРЕЙТИ
КНИГА «ОТДЕЛ ПРОДАЖ. ДРУГОЙ ПОДХОД»
ПЕРЕЙТИ
МЕНТОРСТВО ДЛЯ РОП-ОВ
ПЕРЕЙТИ
АССОЦИАЦИЯ СИСТЕМНЫХ ПРОДАЖ
ПЕРЕЙТИ
АГЕНТСКАЯ ПРОГРАММА
ПЕРЕЙТИ
ПРОВЕРЕННЫЕ ПОДРЯДЧИКИ ДЛЯ ОП
ПЕРЕЙТИ
ПРОВЕРЕННЫЕ СЕРВИСЫ ДЛЯ ОП
ПЕРЕЙТИ


## Возможности платформы (Owner Agent /help)

```json
{
  "name": "Owner Agent API",
  "auth": {
    "header": "X-Owner-Agent-Key: <OWNER_AGENT_API_SECRET>",
    "or": "Authorization: Bearer <OWNER_AGENT_API_SECRET>"
  },
  "notes": [
    "Только чтение: ни один эндпоинт ничего не меняет. Ключи, токены и пароли клиентов не отдаются (маскируются).",
    "Базовый URL: https://systemop.pro/api/owner-agent",
    "{slug} — slug проекта или его UUID (список: GET /tenants)."
  ],
  "how_to_dig": [
    "1. GET /tenants → найти проект; GET /tenants/{slug} → досье (подключения, ИИ, ОКК, ошибки).",
    "2. GET /tenants/{slug}/refs → менеджеры, воронки и этапы (id для фильтров), параметры ОКК, настройки.",
    "3. POST /tenants/{slug}/analytics → вся аналитика за период с фильтрами: менеджеры, ОКК по параметрам и менеджерам, воронка, время на этапах, потери, источники, скорость ответа, пропущенные, выработка, дожим, выводы ИИ, сравнение с прошлым периодом.",
    "4. POST /tenants/{slug}/search → конкретные звонки / переписки / сделки / проверки ОКК, расшифровки и переписки целиком (get_call, get_chat).",
    "5. GET /panel?path=/api/...&tenant={slug} → любой экран панели ровно как его видит пользователь (каталог адресов: GET /routes?q=слово).",
    "6. GET /schema + POST /sql → произвольный SELECT по всей базе платформы, когда готовых срезов мало."
  ],
  "filters": {
    "from": "ГГГГ-ММ-ДД (по умолчанию 30 дней до to)",
    "to": "ГГГГ-ММ-ДД (по умолчанию сегодня)",
    "manager_ids": "[amo_user_id]",
    "pipeline_ids": "[id]",
    "stage_ids": "[id]",
    "channel": "both | calls | chats",
    "modules": "calls, chats, okk_calls, okk_chats, deals, dozim, productivity, lead_loss, insights (по умолчанию все)",
    "use_amounts": "true — учитывать суммы сделок"
  },
  "endpoints": [
    {
      "method": "GET",
      "path": "/help",
      "desc": "Этот каталог"
    },
    {
      "method": "GET",
      "path": "/ping",
      "desc": "Проверка секрета"
    },
    {
      "method": "GET",
      "path": "/system",
      "desc": "PostgreSQL / Redis / Celery"
    },
    {
      "method": "GET",
      "path": "/status",
      "desc": "Сводка по всем активным тенантам"
    },
    {
      "method": "GET",
      "path": "/errors",
      "desc": "Последние platform_logs ошибки (?limit=15)"
    },
    {
      "method": "GET",
      "path": "/tenants",
      "desc": "Список тенантов (?page=&q=&limit=)"
    },
    {
      "method": "GET",
      "path": "/tenants/{slug}",
      "desc": "Полное досье организации"
    },
    {
      "method": "GET",
      "path": "/tenants/{slug}/accounts"
    },
    {
      "method": "GET",
      "path": "/tenants/{slug}/activity"
    },
    {
      "method": "GET",
      "path": "/tenants/{slug}/connections"
    },
    {
      "method": "GET",
      "path": "/tenants/{slug}/ai"
    },
    {
      "method": "GET",
      "path": "/tenants/{slug}/okk"
    },
    {
      "method": "GET",
      "path": "/tenants/{slug}/errors"
    },
    {
      "method": "GET",
      "path": "/tenants/{slug}/diagnose-okk",
      "desc": "Цепочка ОКК (?channel=calls|chats)"
    },
    {
      "method": "GET",
      "path": "/tenants/{slug}/calls-pipeline",
      "desc": "Счётчики звонков по analysis_status + недавние"
    },
    {
      "method": "GET",
      "path": "/tenants/{slug}/refs",
      "desc": "Справочники проекта: менеджеры, воронки/этапы, параметры ОКК, настройки"
    },
    {
      "method": "POST",
      "path": "/tenants/{slug}/analytics",
      "desc": "Аналитика за период: body {from, to, manager_ids, pipeline_ids, stage_ids, channel, modules, use_amounts, sections?}. Без sections — все секции. GET с теми же query-параметрами тоже работает."
    },
    {
      "method": "POST",
      "path": "/tenants/{slug}/search",
      "desc": "Поиск: body {tool, args, filters}. Во всех: date_from, date_to или last_days; query — варианты через |. tool: search_calls / read_calls {manager, query, profanity, deal_status: won|lost|open, direction, min_duration_sec, max_duration_sec, limit; read_calls ещё order: recent|longest, chars} · get_call {call_id} · search_chats / read_chats {manager, query, profanity, deal_status, limit} · get_chat {chat_id} · search_deals {status: open|won|lost|created, stage, manager, query, limit} · okk_findings {param, manager, kind: calls|chats, result: failed|passed, limit} · count_stats {metric: deals_won|deals_lost|deals_created|calls|calls_connected|won_deal_calls|messages_team|messages_clients, group_by: hour|weekday|date|manager|stage|direction, manager} · work_time {manager} · find_insights {query, type: alert|best|feedback|system|loss, limit}"
    },
    {
      "method": "GET",
      "path": "/routes",
      "desc": "Каталог GET-экранов панели (?q= поиск по адресу/описанию)"
    },
    {
      "method": "GET",
      "path": "/panel",
      "desc": "Любой GET-экран панели: ?path=/api/...&tenant={slug}&<параметры экрана>. POST /panel {path, tenant, params} — то же телом."
    },
    {
      "method": "GET",
      "path": "/schema",
      "desc": "Таблицы и колонки базы с пояснениями (?table= одна таблица)"
    },
    {
      "method": "POST",
      "path": "/sql",
      "desc": "Произвольный запрос на чтение: body {sql, limit≤5000 (1000), max_cell≤20000 (4000)}. Отдельный пользователь БД только на чтение, таймаут 30 с, колонки с секретами закрыты."
    },
    {
      "method": "POST",
      "path": "/query",
      "desc": "Универсальный диспетчер action+params (удобно для tool-use)",
      "actions": [
        "help",
        "ping",
        "system",
        "status",
        "errors",
        "tenants",
        "tenant",
        "accounts",
        "activity",
        "connections",
        "ai",
        "okk",
        "tenant_errors",
        "diagnose_okk",
        "calls_pipeline",
        "refs {slug}",
        "analytics {slug, filters..., sections?}",
        "search {slug, tool, args, filters?}",
        "routes {q?}",
        "panel {path, tenant?, params?}",
        "schema {table?}",
        "sql {sql, 
```
