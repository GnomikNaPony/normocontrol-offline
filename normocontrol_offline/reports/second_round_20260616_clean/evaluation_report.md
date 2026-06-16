# Отчет прогона нормоконтроля

Дата: 2026-06-16 18:22:32

## База

- documents: 39
- errors: 1
- references: 1340
- annotations: 455
- findings: 240
- learned_rules: 55

## Документы по типам

- document: 26
- example: 6
- scheme: 3
- standard: 4

## Замечания по категориям

- punctuation: 36
- spacing: 204

## Обучение правил

Речь идет не о fine-tuning весов LLM, а об извлечении проверяемых правил из пар документов.

### Достоверность правил

- 0.00-0.25: 0
- 0.25-0.50: 0
- 0.50-0.75: 6
- 0.75-1.00: 49

### Повторяемость правил

- 1 совпадений: 53
- 5 совпадений: 2

## Прогоны локальной LLM

| Prompt | Run | Score | Seconds | Lines | Chars |
|---|---:|---:|---:|---:|---:|
| checks_ru | 1 | 0.0 | 4.587 | 0 | 0 |
| checks_ru | 2 | 0.0 | 4.101 | 0 | 0 |
| checks_ru | 3 | 0.0 | 4.096 | 0 | 0 |
| checks_ru | 4 | 0.0 | 4.587 | 0 | 0 |
| reference_update | 1 | 0.0 | 4.605 | 0 | 0 |
| reference_update | 2 | 0.0 | 4.093 | 0 | 0 |
| reference_update | 3 | 0.0 | 4.088 | 0 | 0 |
| reference_update | 4 | 0.0 | 4.085 | 0 | 0 |
| report_requirements | 1 | 0.0 | 4.601 | 0 | 0 |
| report_requirements | 2 | 0.0 | 4.624 | 0 | 0 |
| report_requirements | 3 | 0.0 | 4.132 | 0 | 0 |
| report_requirements | 4 | 0.0 | 4.132 | 0 | 0 |