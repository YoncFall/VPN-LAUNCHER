# VPN LAUNCHER — Python edition

Переписка [VPN LAUNCHER BY @YoncFALL](../VPN-LAUNCHER-src/) на Python + PySide6.
Старая PowerShell-версия (v1.0.6) остаётся в `VPN-LAUNCHER-src` и продолжает
поддерживаться — этот проект развивается рядом.

## Статус: этап 1 (ядро) + этап 2 (Windows-мосты) + игровая оболочка окна

- Python 3.12 + PySide6 + pytest + PyInstaller установлены в `venv/`.
- **Ядро портировано и покрыто тестами**: URI-хелперы, парсеры
  протоколов (vless/vmess/trojan/ss/hysteria2/tuic + v2ray-plugin),
  подписки (http/файл/`file://`/b64), генерация конфига sing-box,
  TCP-пинг, состояние, журнал, системный прокси.
- **Паритет с 1.0.6 закреплён golden-тестами**: `tools/make_golden.ps1`
  снимает эталон вывода оригинального `core.ps1` (PowerShell 5.1) на
  фикстурах `tests/fixtures/`; `tests/test_golden.py` сверяет вывод
  Python-порта и гоняет все конфиги через `sing-box check` (3/3 ok).
- **Windows-мосты (этап 2)**: single-instance мьютексы с поднятием окна
  (порт `Host.cs`), повышение прав (`runas`), список запущенных процессов
  (сверен с `Get-RunningExeList` — идентично, 87/87), автозапуск
  (новая функция, см. «Отклонения»). Проверено вживую: реестр Run
  ON/OFF, UAC-команда (мок), поиск окна первого экземпляра.
- **Окно в игровом стиле 1.0.6**: тёмно-синий градиент фона, неоновая шапка
  со свечением логотипа (без подчёркивания — убрано по просьбе), градиентные
  линии: кант шапки, полоска карточки, рамка карточки по рёбрам и через
  скругления углов, разделители с градиентом, карточка со всей
  раскладкой: поле подписки, кнопки, секции, радио-режимы, статус-строка.
- Дальше: списки со скроллбарами и попап-пикер (этап 4),
  воркеры/запуск VPN (этап 5), сборка PyInstaller (этап 6).

## Запуск

```powershell
.\run.ps1                                   # окно приложения
venv\Scripts\python.exe -m pytest           # тесты (142)

# переснять golden-эталон с текущей PS-версии (после правок core.ps1);
# -SingBox необязателен: без него пропускается только прогон `sing-box check`
powershell -ExecutionPolicy Bypass -File tools\make_golden.ps1 `
    -Core ..\VPN-LAUNCHER-src\src\core.ps1 -SingBox <путь\sing-box.exe>

# движок для `sing-box check`, если он не в путях по умолчанию:
$env:SING_BOX_EXE = "C:\...\sing-box.exe"

# снимок окна в файл и выход (скриншотная сверка с 1.0.6)
$env:VPN_SHOT = "C:\Temp\shot.png"; venv\Scripts\python.exe app.py
```

## Структура

```
app.py                 точка входа (+ режим VPN_SHOT)
vpn_launcher/
  paths.py             корень установки, state/config/log, SOCKS-порт
  core/                логика без Qt (тестируется pytest)
    uris.py            парсеры URI+протоколов [ГОТОВО]
    latency.py         TCP-пинг             [ГОТОВО]
    state.py           state.json           [ГОТОВО]
    log.py             журнал               [ГОТОВО]
    subscription.py    подписки             [ГОТОВО]
    config.py          конфиг sing-box      [ГОТОВО]
  win/                 реестр/права/процессы
    proxy.py           системный прокси     [ГОТОВО]
    autostart.py       реестр Run (новое)   [ГОТОВО]
    elevate.py         повышение прав       [ГОТОВО]
    mutex.py           single instance      [ГОТОВО]
    proc.py            список процессов     [ГОТОВО]
    proc.py start/stop sing-box             [этап 5]
  ui/
    theme.py           палитра/шрифты       [ГОТОВО]
    window.py          главное окно+раскладка [ГОТОВО]
    widgets/
      button.py        GameButton (5 скинов) [ГОТОВО]
      field.py         GameField             [ГОТОВО]
      card.py          GameCard              [ГОТОВО]
      frame.py         GameFrame             [ГОТОВО]
      radio.py         сегмент-радио         [ГОТОВО]
      divider.py       разделители           [ГОТОВО]
      led.py           индикатор             [ГОТОВО]
      title_bar.py     шапка с логотипом     [ГОТОВО]
      neon_list.py     списки + скроллбар    [этап 4]
      picker.py        попап-пикер           [этап 4]
      scroll_bar.py    свой скроллбар        [этап 4]
  workers/             фоновые задачи Qt     [этап 5]
tests/                 pytest
  fixtures/            подписки-фикстуры     [ГОТОВО]
  golden/              эталон вывода PS 1.0.6 [ГОТОВО]
tools/
  make_fixtures.py     генератор фикстур     [ГОТОВО]
  make_golden.ps1      снимок golden с core.ps1 [ГОТОВО]
```

## Правило поведения

Поведение VPN обязано совпадать с 1.0.6: конфиги sing-box сверяются по
golden-файлам, `sing-box.exe` и установщик не меняются.

### Отклонения от 1.0.6 (все помечены в комментариях кода)

Визуал:

- подсказка серверов перенесена на строку подписи «СЕРВЕРЫ» — в 1.0.6 она
  перекрывалась с колонкой ПИНГ.

Windows-мосты (на VPN не влияют):

- **автозапуск — новой функции в 1.0.6 нет** (в PLAN-PYTHON.md этап 2);
  обычный HKCU Run, включается/выключается вручную;
- список процессов собран через Toolhelp32 вместо `Get-Process` (без
  psutil) — сверен с `Get-RunningExeList` на этом ПК: идентично 87/87;
- `acquire_instance()` идемпотентен в рамках одного процесса (Host.cs
  одноразовый, такой case там не возникает).

Ядро (на поведение VPN не влияет):

- подписка: тело HTTP-ответа сначала декодируется как UTF-8, иначе ANSI
  (1.0.6 через WebClient всегда ANSI/cp1251) — разница видна только в
  display-именах с «сырой» кириллицей;
- запись `config.json`: `json.dumps` вместо `ConvertTo-Json` PS 5.1 —
  формат красивее, семантика та же, `sing-box check` принимает оба;
- текст ошибки `sing-box check`: UTF-8 вместо ANSI-чтения PS 5.1.

### Сохранённые особенности 1.0.6 (не чиним ради паритета)

- vmess: поле `type` из JSON (тип заголовка) в `Get-QueryVal` идёт раньше
  `net` — ws-transport у vmess обычно не строится;
- vmess + tls: `$q` в PS пересобирается только из security/sni/fp/alpn,
  transport теряется совсем;
- обычная (не-b64) подписка, начинающаяся с комментария, в 1.0.6
  склеивается в одну строку и не парсится — фикстура намеренно
  начинается с URI;
- `Select-Object -Unique` для списка direct-apps регистрозависим
  (проверено на PS 5.1) — Python повторяет это.
