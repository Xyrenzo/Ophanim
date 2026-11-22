# P6 — исследовательская основа (оглавление)

Читать в этом порядке: сначала обязательные ограничения, затем исследовательские документы, которые на
них опираются.

Это рабочие документы конкретных этапов разработки. Каждый из них описывает состояние кода на дату своего
этапа; ссылки на строки (`L123`) и статусы относятся к той версии. Актуальное состояние — в разделах
«Обновления статуса по этапам» матрицы трассировки и в отчётах `p6c_phase1`–`p6c_phase3`, а измеренные
результаты текущей версии — в [`../results.md`](../results.md).

| № | документ | содержание |
|---|---|---|
| 1 | [p6_official_compliance_audit.md](p6_official_compliance_audit.md) | аудит по официальным определениям проверок (2026-11-20): блокирующие пробелы, несоответствующие соглашения, порядок исправлений |
| 2 | [p6_traceability_matrix.md](p6_traceability_matrix.md) | каждое официальное требование (адаптер, C01–C20, D01–D20, тесты 1–20, M01–M12, P01–P20, инженерия) → файл, статус, доказательство, необходимое изменение, приоритет |
| 3 | [p6_architecture_constraints.md](p6_architecture_constraints.md) | обязательные ограничения на интерфейс, изоляцию, matcher и данные для всей дальнейшей работы |
| 4 | [p6_repository_audit.md](p6_repository_audit.md) | что на самом деле делает код: жизненный цикл, наблюдения, пять инструментов, награда, базовые политики, измерения, расхождения |
| 5 | [p6_problem_formulation.md](p6_problem_formulation.md) | постановка в виде POMDP, структурные свойства, пространство действий, исследовательские задачи |
| 6 | [p6_algorithm_review.md](p6_algorithm_review.md) | BC/DAgger, PPO, семейство DQN, рекуррентный PPO, Decision Transformer, offline RL, нейросимвольные подходы, LLM-агенты; фреймворки |
| 7 | [p6_agent_architecture.md](p6_agent_architecture.md) | предлагаемая архитектура агента: информационная граница, представление действий и наблюдений, память, интерфейсы |
| 8 | [p6_experiment_protocol.md](p6_experiment_protocol.md) | разделение данных, метрики, статистика, 12 исследовательских вопросов, абляции |
| 9 | [p6_implementation_roadmap.md](p6_implementation_roadmap.md) | исправления соответствия P6-C, затем этапы P7–P13 с критериями приёмки |
| 10 | [p6_references.md](p6_references.md) | проверенные источники и страницы документации |
| 11 | [p6c_phase1_adapter_report.md](p6c_phase1_adapter_report.md) | отчёт P6-C, этап 1: адаптер жюри |
| 12 | [p6c_phase2_matcher_report.md](p6c_phase2_matcher_report.md) | отчёт P6-C, этап 2: точный matcher и поиск по идентификаторам |
| 13 | [p6c_phase3_generator_report.md](p6c_phase3_generator_report.md) | отчёт P6-C, этап 3: соответствие генератора официальным сценариям |

Доказательства (перезапускаемые, только чтение): [`evidence/p6_official_checks.py`](evidence/p6_official_checks.py)
→ [`evidence/p6_official_checks.out.txt`](evidence/p6_official_checks.out.txt) (вывод на этапе P6) и
[`evidence/p6c_phase2_official_checks.out.txt`](evidence/p6c_phase2_official_checks.out.txt) (вывод после
этапа 2); [`evidence/p6_measure.py`](evidence/p6_measure.py) → [`evidence/p6_measure.out.json`](evidence/p6_measure.out.json).
Запуск из корня репозитория: `PYTHONPATH=src python docs/research/evidence/<script>.py`. Сохранённые файлы
`.out.*` — снимки на дату своего этапа; на текущем коде (ENV 0.3.0) `p6_official_checks.py` даёт 46 PASS,
0 FAIL (2026-11-22).

На этапе P6 в `src/`, `tests/`, `configs/` и `data/` ничего не менялось.
