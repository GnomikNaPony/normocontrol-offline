# Нормоконтроль Offline

Репозиторий содержит прототип локальной программы нормоконтроля документов и
материалы для обучения/проверки.

Основные файлы:

- [ИНСТРУКЦИЯ.md](ИНСТРУКЦИЯ.md) - подробная установка, запуск и рабочие
  сценарии.
- [normocontrol_offline/README.md](normocontrol_offline/README.md) - краткое
  описание программы.
- [normocontrol_offline/docs/ARCHITECTURE.md](normocontrol_offline/docs/ARCHITECTURE.md)
  - архитектура.
- [normocontrol_offline/docs/MODELS.md](normocontrol_offline/docs/MODELS.md) -
  выбор локальных моделей.

Быстрый запуск:

```bash
cd normocontrol_offline
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```
