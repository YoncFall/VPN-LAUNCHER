# VPN LAUNCHER — Python edition

Переписка [VPN LAUNCHER BY @YoncFALL](../VPN-LAUNCHER-src/) на Python + PySide6.
Старая PowerShell-версия (v1.0.6) остаётся в `VPN-LAUNCHER-src` и продолжает
поддерживаться — этот проект развивается рядом.

## Статус: этап 0 (среда и каркас)

- Python 3.12 + PySide6 + pytest + PyInstaller установлены в `venv/`.
- Ядро портировано и покрыто тестами: URI-хелперы, TCP-пинг, состояние, журнал.
- Каркас главного окна (frameless 620x726, палитра и шрифты 1.0.6).
- Остальное — по этапам плана (см. `../VPN-LAUNCHER-src/PLAN-PYTHON.md`).

## Запуск

```powershell
.\run.ps1          # окно приложения
.\run.ps1 -m pytest  # тесты (или: venv\Scripts\python.exe -m pytest)
```

## Структура

```
app.py                 точка входа
vpn_launcher/
  paths.py             корень установки, state/config/log, SOCKS-порт
  core/                логика без Qt (тестируется pytest)
    uris.py            парсеры URI          [ГОТОВО]
    latency.py         TCP-пинг             [ГОТОВО]
    state.py           state.json           [ГОТОВО]
    log.py             журнал               [ГОТОВО]
    subscription.py    подписки             [этап 1]
    config.py          конфиг sing-box      [этап 1]
  win/                 реестр/права/процессы
    proxy.py           системный прокси     [ГОТОВО]
    autostart.py, elevate.py, mutex.py, proc.py   [этап 2]
  ui/
    theme.py           палитра/шрифты       [ГОТОВО]
    window.py          главное окно         [этап 0-3]
    widgets/           списки/кнопки/поля   [этап 3-4]
  workers/             фоновые задачи Qt    [этап 5]
tests/                 pytest
```

## Правило поведения

Поведение VPN обязано совпадать с 1.0.6: конфиги sing-box сверяются по
golden-файлам, `sing-box.exe` и установщик не меняются.
