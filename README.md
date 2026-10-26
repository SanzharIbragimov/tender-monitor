# Мониторинг тендеров и RFP на ИТ-услуги — прототип

Каждый день собирает лоты с порталов закупок РК, оценивает релевантность
(правила → LLM) и рассылает email-дайджест. Работает только с публичными данными, заявки не подаёт.

```
Планировщик → Коннекторы → Нормализация и дедупликация → SQLite → Оценка → Дайджест (SMTP)
                   ↓                                                   ↑
             журнал + алерт                                    config.yaml
```

## Запуск

```bash
cp .env.example .env          # токен goszakup, SMTP, ключ LLM
docker compose up -d --build  # сбор в 07:00, рассылка в 08:00 по Астане
```

Без Docker:

```bash
pip install -r requirements.txt
python -m app.main run                          # один полный прогон
python -m app.main digest --dry-run out.html    # дайджест в файл вместо письма
python -m app.main export --from 2026-11-01 --to 2026-11-15 --out lots.csv
python -m app.main probe --source zakup_sk      # сырой ответ источника для сверки полей
python -m app.main report --from 2026-11-01 --to 2026-11-15 --sample control.csv   # отчёт о качестве
python demo.py                                  # демо на тестовых данных, без сети
pytest -q                                       # автотесты
```

Подробно о развёртывании, настройке, добавлении источника и пилоте — [docs/deploy.md](docs/deploy.md).

## Настройка (config.yaml, без изменения кода)

- `scoring.directions.*.keywords` — основы слов и их веса (рус. и каз.); фраза из нескольких основ ловит любые окончания.
- `scoring.stop_words` — штрафы за нерелевантные слова.
- `scoring.prefilter_threshold` — ниже порога лот не отправляется в LLM.
- `digest.threshold`, `max_lots`, `urgent_days`, `send_at`, `recipients`, `alert_to`.

## Как добавить источник

- **Сайт без API:** новый блок `type: html` в `sources` с `list_url` и CSS-селекторами (`item`, `title`, `link`, `organizer`, `deadline`, `budget`). Код не меняется.
- **Сайт с API или JSON:** класс-наследник `Source` с методом `fetch()` по образцу `app/sources/goszakup.py` и регистрация в `app/sources/__init__.py`.

## Как устроено

| Требование ТЗ | Где |
| --- | --- |
| Сбор, сбой источника не останавливает остальные | `app/main.py: collect` |
| robots.txt, ограничение частоты, повторы | `app/sources/base.py` |
| Единая структура, дубли между источниками, изменения лота | `app/models.py`, `app/db.py: upsert` |
| Оценка 0–100, направление, пояснение | `app/scoring/` |
| Дайджест, горящие сроки, пустой дайджест | `app/digest.py`, `app/templates/digest.html` |
| Журнал запусков, алерт ответственному | таблица `runs`, `digest.alert` |
| CSV за период | `python -m app.main export` |
| Схема и миграции в репозитории | `migrations/` |
| Отчёт о качестве по критериям приёмки | `python -m app.main report`, `app/quality.py` |

## Статус прототипа

| Источник | Состояние |
| --- | --- |
| goszakup.gov.kz | Запрос сверен со схемой OWS v3: `Lots` по `indexDate`, пагинация `extensions.pageInfo`, коды ЕНС ТРУ из `Plans.refEnstruCode`. Нужен только токен. |
| zakup.sk.kz | Коннектор к JSON-эндпоинту сайта (`eprocsearch/api/external/4dv3rts/filter`). Выключен: имена параметров страниц и полей ответа сверить командой `python -m app.main probe --source zakup_sk` или в DevTools. |
| nadloc.kz | Не исследован: селекторы заполняются на этапе 1. |
| Ещё 2 источника | Выбираются на этапе 1. |

- Автотесты (14) на тестовых данных: разбор ответов goszakup и zakup.sk.kz, HTML-страниц, дедупликация, изменения, оценка правилами (рус. и каз.), разбор ответа LLM, дайджест, метрики приёмки.
- Коды ЕНС ТРУ в `enstru_prefixes` — допущение, проверить по справочнику.
- Тестовые лоты в `tests/fixtures` выдуманы и служат только для проверки логики.
