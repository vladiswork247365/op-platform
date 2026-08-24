# Наполнение сайта (снимок 2026-08-24T07:55:08Z)


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
ПАНЕЛЬ УПРАВЛЕНИЯ ДЛЯ РОПОВ
ПЕРЕЙТИ
ЗАКРЫТАЯ АССОЦИАЦИЯ СИСТЕМНЫХ ПРОДАЖ
ПЕРЕЙТИ
УСИЛЕНИЕ ОТДЕЛОВ ПРОДАЖ
ПЕРЕЙТИ
КНИГА «ОТДЕЛ ПРОДАЖ. ДРУГОЙ ПОДХОД»
ПЕРЕЙТИ
ПЛАТФОРМА УЧАСТНИКОВ АССОЦИАЦИИ
ПЕРЕЙТИ
АГЕНТСКАЯ ПРОГРАММА
ПЕРЕЙТИ
БОТ-ПОМОЩНИК
ПЕРЕЙТИ
ПРОВЕРЕННЫЕ ПОДРЯДЧИКИ ДЛЯ ОП
ПЕРЕЙТИ
ПРОВЕРЕННЫЕ СЕРВИСЫ ДЛЯ ОП
ПЕРЕЙТИ
БЛОГ О СИСТЕМЕ В ОТДЕЛЕ ПРОДАЖ
ПЕРЕЙТИ
МЕНТОРСТВО ДЛЯ РОП-ОВ
ПЕРЕЙТИ
ИНВЕСТИЦИОННАЯ ПРОГРАММА
СКОРО
БИБЛИОТЕКА КЕЙСОВ
СКОРО
БИБЛИОТЕКА ОТЗЫВОВ
СКОРО
БИБЛИОТЕКА АУДИТОВ
СКОРО


## Возможности платформы (Owner Agent /help)

```json
{
  "name": "Owner Agent API",
  "auth": {
    "header": "X-Owner-Agent-Key: <OWNER_AGENT_API_SECRET>",
    "or": "Authorization: Bearer <OWNER_AGENT_API_SECRET>"
  },
  "notes": [
    "Read-only. Значения клиентских API-ключей не отдаются.",
    "Базовый URL: https://<host>/api/owner-agent",
    "Для Claude: сначала GET /help, затем нужные GET или POST /query."
  ],
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
        "calls_pipeline"
      ]
    }
  ]
}
```
