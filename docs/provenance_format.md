# Формат `provenance.json` (ENV_VERSION 0.3.0)

**Назначение.** Provenance — запись о том, *как* был создан эпизод; она доступна только оценщику. В ней
хранятся входные параметры генерации, соответствие внутренних ключей публичным идентификаторам, законные
ложные следы, документы, подготовленные для сценариев, каждая внесённая ошибка в виде преобразования
«до/после» и полные чистые книги до любых изменений. Благодаря этому каждую проблему эталона можно
проверить независимо (официальные проверки, блок 2, условие 1: «до внесения ошибки книги согласованы;
история provenance и исходные документы позволяют выполнить независимую проверку»).

**Где лежит и кому принадлежит.** `<episode_dir>/evaluator/provenance.json`. Файл записывает
`ophanim.generator.episode.generate_episode` (через `judge_adapter.generate_episode`) вместе с
`evaluator/truth.json`. Он принадлежит оценщику и жюри.

**Агенту никогда не показывается.**

* Окружение в закрытом режиме никогда не читает каталог `evaluator/`, а ни один инструмент не имеет
  доступа к файлам.
* Seed, конфигурация, метки ложных следов и строки «до/после» раскрыли бы ответ или позволили бы его
  восстановить.
* Это закреплено тестами: проверки утечек в каждом наблюдении и каждой траектории, прогон закрытого эпизода
  с удалённым `evaluator/` и AST-правила, не позволяющие коду агента импортировать генератор или оценщик.

## Поля верхнего уровня

| поле | тип | содержимое |
|---|---|---|
| `schema_version` | string | версия схемы публичных данных (`"1.0"`) |
| `env_version` | string | `ENV_VERSION` кода, создавшего эпизод (`"0.3.0"`) |
| `episode_id` | string | тот же, что в `manifest.json` и `truth.json` |
| `generation` | object | `seed` (int), `secret_used` (bool: генерация подписана `OPHANIM_EVAL_SECRET`), `config` (полностью развёрнутый `EpisodeConfig`, включая значения по умолчанию, например `allocation_mode`) |
| `company` | object | `profile` (имя профиля Financial DNA), `base_currency`, `offset_minutes` (смещение компании от UTC), `period` (`[start, end]` — даты ISO, включительно) |
| `id_map` | object | внутренний ключ → публичный идентификатор. Ключи: `S..` поставщик → `entity_id`; `I....` счёт → `invoice_id`; `P....` платёж → `payment_id`; `R.....` строка главной книги → `row_id`; `doc:I....` / `doc:P....` → `doc_id`. Охватывает объединение чистых и изменённых книг |
| `distractors` | list | законные ложные следы (см. ниже); только внутренние ключи |
| `scenario_carriers` | list | правильные документы, заложенные *до* снимка чистых книг, чтобы у сценария гарантированно был носитель: `{"scenario", "payment", "invoices"}`. `scenario` — одно из `fx_partial_payment_boundary`, `fx_invoice_unapplied_payment`, `allocation_missing`, `allocation_partial` |
| `injections` | list | по одной записи на каждую проблему эталона (см. ниже) |
| `pre_mutation` | object | `validation_problems` (список; у сгенерированного эпизода всегда пуст, потому что чистые книги обязаны выполнять все бухгалтерские равенства) и `tables` (`ledger`, `invoices`, `payments`, `fx`: полные чистые публичные таблицы в публичных идентификаторах до внесения ошибок) |

### `distractors[]`

Каждая запись — `{"kind", "note", "invoices"?, "payments"?}` с внутренними ключами:

| kind | значение |
|---|---|
| `recurring_same_amount` | ежемесячные регулярные счета с одинаковой суммой (разный `vendor_ref`) |
| `repeat_order_same_amount` | тот же поставщик и сумма, другие `vendor_ref` и дата |
| `vendor_ref_collision` | два разных поставщика используют один номер счёта |
| `reversed_duplicate` | дубль, полностью сторнированный в периоде (чистый эффект нулевой) |
| `split_payment` | один счёт оплачен двумя платежами, оба распределены (D02; гарантирован при `distractors` normal/high) |
| `partial_payment` | счёт оплачен частично; платёж распределён полностью |
| `batch_payment` | один платёж закрывает несколько счетов |
| `unidentified_payment` | платёж без расшифровки, правильно учтённый в Suspense |
| `correct_refund` | `payments = [возвращаемый платёж, возврат]`: поставщик полностью вернул платёж без расшифровки (D03; гарантирован при `distractors` normal/high) |
| `boundary_utc_date` | счёт в иностранной валюте, относящийся к периоду, у которого дата UTC попадает в соседний месяц (D05) |

### `injections[]`

`{"issue_id", "type", "scenario", "cause", "details"}`:

* `issue_id` совпадает с `issue_id` в `truth.json`;
* `type` — один из четырёх типов ошибок;
* `scenario` — `"single"` или имя взаимодействующего сценария;
* `cause` — понятное человеку причинное объяснение с внутренними ключами;
* `details` зависит от типа; все ключи внутри него внутренние:

| тип | ключи `details` |
|---|---|
| `duplicate_invoice` | `original`, `copy`, `rows_added` (проводка копии) |
| `payment_allocation` | `payment`, `invoice`, `allocation_kind` (`missing` \| `partial`), `rows_before`, `rows_after` (проводка платежа) |
| `fx_rate` (счёт) | `invoice`, `wrong_rate_date`, `wrong_rate_cause`, `rows_before`, `rows_after` |
| `fx_rate` (платёж) | `payment`, `wrong_rate_date`, `wrong_rate_cause`, `rows_before`, `rows_after` |
| `period_attribution` (счёт) | `invoice`, `local_date`, `utc_date`, `rows_added` |
| `period_attribution` (платёж) | `payment`, `invoice`, `local_date`, `utc_date`, `rows_added` |

Снимки строк имеют вид `{"row", "account", "debit_minor", "credit_minor", "invoice", "payment", "role"}`.
В `row`, `invoice` и `payment` лежат внутренние ключи; перевести их в публичные позволяет `id_map`.
`role` — внутренняя роль проводки, одна из:

* `expense`, `ap`, `ap_clear`, `bank`, `suspense`, `suspense_refund`, `fx`;
* `reversal_ap`, `reversal_expense`.

## Связь с `truth.json`

`truth.json` говорит, *что* не так, в публичных терминах: `issue_id`, `type`, `affected_ids`,
`expected_amount_minor`, `currency`, `allowed_evidence_sets`, `scenario`, а на уровне файла —
`tolerance_minor`.

Provenance говорит, *как* возникла каждая проблема. Каждый `truth.issues[*].issue_id` встречается в
`provenance.injections` ровно один раз. У чистого эпизода пустой эталон и пустой `injections`, но ложные
следы в нём всё равно есть.

## Как его использует код оценщика

* `evaluator/verifier.py` сверяет `pre_mutation.tables` независимым аудитором и требует ноль расхождений и
  ноль аномалий. Затем он сверяет опубликованные таблицы и требует ровно проблемы эталона.
* `evaluator/metamorphic.py` через `id_map` отображает идентификаторы между двумя представлениями одного
  эпизода.
* `adapter.load_sealed_episode` загружает файл вместе с `truth.json`; сама оценка использует только
  `truth.json`.
* Тесты читают `distractors`, `scenario_carriers` и `injections`, чтобы проверить ложные следы и причинные
  детали.

## Парные проверки (замена идентификаторов жюри)

Когда жюри заменяет идентификаторы в своей копии эпизода, в provenance согласованно нужно заменить:

* **значения** `id_map`;
* все идентификаторы внутри `pre_mutation.tables`.

Все остальные ссылки в provenance — внутренние ключи; это не публичные идентификаторы, и заменять их не
нужно.

## Версии и совместимость

Файл побайтно воспроизводится из (seed, config, секрет, `ENV_VERSION`). Изменение его полей или их смысла
требует повышения `ENV_VERSION`. Поле `scenario_carriers` добавлено в 0.3.0. Потребители должны
игнорировать неизвестные ключи и не должны полагаться на порядок `distractors`: он следует порядку
генерации.
