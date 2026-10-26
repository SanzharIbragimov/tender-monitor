# Развёртывание и эксплуатация

Развёртывание занимает 20–30 минут при готовых доступах.

## 1. Что подготовить

| Что | Где взять | Переменная |
| --- | --- | --- |
| Сервер Linux с Docker и Docker Compose, 2 vCPU, 4 ГБ RAM, 20 ГБ диска | инфраструктура Заказчика | — |
| Исходящий HTTPS к порталам закупок и `api.anthropic.com` | сетевой администратор | — |
| Токен OWS goszakup | заявка на ows.goszakup.gov.kz | `GOSZAKUP_TOKEN` |
| Ключ LLM (необязательно: без него оценка только по правилам) | console.anthropic.com | `ANTHROPIC_API_KEY` |
| Почтовый ящик для отправки, SMTP с TLS | почтовый администратор | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` |

## 2. Установка

```bash
git clone <репозиторий> tender-monitor && cd tender-monitor
cp .env.example .env            # вписать токен, ключ и SMTP
nano config.yaml                # recipients, alert_to, при необходимости send_at и threshold
docker compose up -d --build
```

## 3. Проверка

```bash
docker compose exec tender-monitor python -m app.main collect     # сбор, в логе — число лотов по источникам
docker compose exec tender-monitor python -m app.main score       # оценка
docker compose exec tender-monitor python -m app.main digest --dry-run /data/check.html   # письмо в файл
docker compose exec tender-monitor python -m app.main digest      # настоящая отправка
docker compose logs -f                                            # расписание: «сбор 07:00, рассылка 08:00»
```

Если сбор источника упал, ответственному из `alert_to` приходит письмо, остальные источники продолжают работу.

## 4. Настройка без изменения кода

Все настройки — в `config.yaml`, после правки: `docker compose restart`.

- **Ключевые слова** (`scoring.directions.*.keywords`): основа слова и вес. Основа ловит любые окончания: `разработк` → «разработка», «разработки». Фраза из нескольких основ ловит словосочетание: `информационн систем`.
- **Стоп-слова** (`scoring.stop_words`): основа и штраф.
- **Порог дайджеста** (`digest.threshold`): поднять — меньше лишних лотов, опустить — меньше пропусков.
- **Порог LLM** (`scoring.prefilter_threshold`): лоты ниже порога не отправляются в LLM.
- **Получатели, время, размер дайджеста**: `digest.recipients`, `send_at`, `max_lots`, `urgent_days`.
- **Источники**: `sources.<имя>.enabled: true/false`.

## 5. Добавление источника

**Площадка без API (обычные HTML-страницы).** Новый блок в `sources`, код не меняется:

```yaml
  new_portal:
    type: html
    enabled: true
    list_url: https://portal.kz/tenders?page={page}
    delay_sec: 2.0
    max_pages: 5
    selectors:            # CSS-селекторы, подобрать в DevTools браузера
      item: ".tender-row"
      title: ".tender-title"
      link: ".tender-title a"
      organizer: ".customer"
      deadline: ".end-date"
      budget: ".sum"
```

Перед включением проверить robots.txt и условия портала; сервис сам не скачивает страницы, запрещённые robots.txt.

**Площадка с API или JSON-запросом в интерфейсе.** Класс-наследник `Source` с методом `fetch(since_days) -> list[Lot]` в `app/sources/`, по образцу `goszakup.py` или `zakup_sk.py`; новый `type` регистрируется в `app/sources/__init__.py`. Сырой ответ источника для сверки полей: `python -m app.main probe --source <имя>`.

К новому коннектору добавляется тест с сохранённым ответом в `tests/fixtures/`.

## 6. Пилот и приёмка

1. До пилота Заказчик размечает 100 лотов в CSV: колонка `key` (`источник:id`, видно в выгрузке CSV) или `url`, колонка `label` (1 — релевантный, 0 — нет).
2. 14 дней сервис работает по расписанию.
3. Отчёт о качестве по критериям раздела 9 ТЗ:

```bash
python -m app.main report --from 2026-11-01 --to 2026-11-15 --sample control.csv --out quality_report.md
python -m app.main export --from 2026-11-01 --to 2026-11-15 --out pilot_lots.csv
```

Отчёт показывает долю успешных запусков по источникам, полноту полей на случайной выборке из 100 лотов, долю повторов в дайджестах, серию дней доставки, recall и precision на контрольной выборке и таблицу ошибок с пояснениями сервиса.

## 7. Частые проблемы

| Симптом | Причина и решение |
| --- | --- |
| goszakup: `401` | Токен не задан или истёк — обновить `GOSZAKUP_TOKEN` |
| Источник даёт 0 лотов, нет ошибок | Сменилась вёрстка — обновить селекторы или поля в `config.yaml` |
| `robots.txt запрещает` | Источник не разрешает автоматический сбор — согласовать замену |
| В письме «оценка по правилам: LLM недоступна» | Нет ключа, исчерпан лимит или сбой API — лоты всё равно оценены правилами |
| Письмо не пришло | `docker compose logs`, таблица `runs` (stage = digest), настройки SMTP |
