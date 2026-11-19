# Пропатченный sing-box (REALITY + Xray 26.9.8+)

## Зачем

Серверы подписки работают на Xray-core новее v26.9.8. Такой сервер в REALITY
требует, чтобы в ClientHello был обмен ключами `X25519MLKEM768`; иначе он
молча уводит соединение на маскировочный сайт, а клиент видит
`reality verification failed`.

Стоковый sing-box вырезает этот обмен ключами, поэтому не подключался ни к
одной ноде подписки (проверено на 1.12.14, 1.13.21, 1.14.2, 1.14.4,
1.15.0-alpha.13). Официальный Xray-core те же ноды открывает.

Второе отличие: Xray с v26.7.11 сравнивает версию клиента REALITY (SessionID)
с `minClientVer`; sing-box присылает `1.8.1` и получает отказ. Патч пишет
`26.9.8`.

## Что меняется

`common/tls/reality_client.go`:

* `X25519MLKEM768` больше не вырезается безусловно: гибридная группа остаётся,
  если выбранный uTLS-fingerprint присылает и группу, и ключ; иначе убираются
  обе половины (группа без ключа вызывает HelloRetryRequest, который REALITY
  не умеет пересылать).
* Версия клиента в SessionID: `1.8.1` → `26.9.8`.
* Убран повторный `BuildHandshakeState()` (после правки расширений он не нужен).

Патч: [`reality-mlkem.patch`](reality-mlkem.patch).

## Сборка

Исходники: <https://github.com/SagerNet/sing-box/releases/tag/v1.14.4>
(архив `sing-box-1.14.4.zip`). Go 1.27.4, `CGO_ENABLED=0`, `GOOS=windows`,
`GOARCH=amd64`.

```powershell
$tags = (Get-Content release\DEFAULT_BUILD_TAGS_WINDOWS -Raw).Trim()
$shared = (Get-Content release\LDFLAGS -Raw).Trim()
$ld = "-X 'github.com/sagernet/sing-box/constant.Version=1.14.4' $shared -s -w -buildid="
go build -trimpath -o dist\sing-box.exe -tags "$tags" -ldflags "$ld" .\cmd\sing-box
```

Штатные теги Windows-сборки, ничего не добавлено от себя.

## Проверка

* `sing-box version` → `1.14.4`.
* Ноды подписки (15.11.2026): через патченный движок работают node-1, node-3,
  node-5, node-10. node-2/4/6/9 принимают REALITY, но рвут TLS уже на сервере
  (проблема провайдера), node-7/8 не отвечают по TCP.
* SHA-256: `EF54F7B7DE1CDEA632614D1492249CB07C5EBF44D1D33FF3C6E9459A512C63D5`
  (совпадает с `ENGINE_SHA256` в `vpn_launcher/win/proc.py`).

## При обновлении sing-box

1. Взять новый тег, применить патч (если файл ещё существует в том же виде).
2. Собрать по команде выше, заменить `sing-box.exe` в корне репозитория.
3. Обновить `ENGINE_SHA256` в `vpn_launcher/win/proc.py`.
4. Прогнать `pytest` (тест `test_engine_hash_pinned` ловит забытый хэш).
5. Проверить подключение к живой ноде Reality.
