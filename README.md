# Home assistant (Pi + Windows + Яндекс Станция)

Три части. Клиент DeepSeek на Pi и прокси колонки — разные процессы: свой ключ, свой URL, своя модель.

- `pi/` — Raspberry Pi: микрофон, колонки, wake-фразы и команды. Ответ пишет DeepSeek Responses API.
- `windows/` — Windows: распознавание Vosk и синтез Piper.
- `deepseek-bridge/` — прокси на отдельной Яндекс Станции. Распознавание и озвучка остаются в Яндексе, текст ответа пишет DeepSeek. К Pi и к `windows/` не подключается.

## Windows

Первичная установка (скачивает модели, при необходимости ставит Python через winget):

```powershell
cd windows
.\install.ps1
.\.venv\Scripts\python.exe -m jarvis_win
```

Починить venv и зависимости без переустановки Python:

```powershell
cd windows
.\fix.ps1
```

Из Git Bash: `./fix.sh`

Автозапуск при загрузке и перезапуск после падения (Планировщик заданий; перезапуск не чаще раза в минуту):

```powershell
cd windows
.\install-service.ps1
```

Снять: `.\install-service.ps1 -Uninstall`

Откройте в брандмауэре TCP `9700` и `9701` для IP платы.

STT (Vosk) и TTS (Piper) на Windows **не грузятся при старте** процесса: Pi после подключения шлёт `health`, при необходимости `reload_modules` (`stt`, `tts` или `all`). Тот же цикл повторяется каждые `WINDOWS_HEALTH_INTERVAL_SEC` (по умолчанию 600) в `.env` на Pi. Control-канал: `health` / `reload_result` с полями `stt` и `tts` (`state`: `unloaded` | `loading` | `ready` | `error`). Синтез `speak` выполняется в отдельном потоке, чтобы `health` отвечал и при долгом Piper. Таймаут синтеза: `PIPER_SYNTH_TIMEOUT_SEC` (default 120), probe при reload TTS: `PIPER_PROBE_TIMEOUT_SEC` (default 30).

Python-пакет **vosk 0.3.50** собирается локально через Docker (`install-vosk.ps1` + `Dockerfile.vosk-win`), не с PyPI. Нужен **Docker Desktop** (Linux containers); первая сборка Kaldi/MinGW может занять часы. Повторный `fix.ps1` ставит кэш из `third_party/vosk-api/wheelhouse`. Пересобрать: `VOSK_FORCE_REBUILD=1`.

## Raspberry Pi

```bash
cd pi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# укажите WINDOWS_HOST
PYTHONPATH=. python -m jarvis_pi
```

Wake-фразы по умолчанию: `компьютер`, `джарвис`, `прослушка` (`WAKE_WORDS` в `.env`).

Ответ на команду пишет DeepSeek Responses API: ключ `DEEPSEEK_API_KEY`, модель `DEEPSEEK_MODEL` (по умолчанию `deepseek-flash`), адрес `DEEPSEEK_RESPONSES_URL` (по умолчанию `https://api.deepseek.com/responses`) в `pi/.env`. У прокси колонки другие настройки, см. ниже.

Во время ответа TTS микрофон остаётся включённым (AEC по reference из колонки). Wake-фразу по-прежнему распознаёт Windows STT: она прерывает озвучку, играет `accept.wav` и открывает окно команды. На Pi отдельная модель Vosk не нужна. `AEC_BACKEND=off` отключает WebRTC AEC. Задержку эха задаёт `AEC_STREAM_DELAY_MS`.

Свет и другие устройства Home Assistant — tools `get_home` и `control_home`. Адрес и долгоживущий токен: `HA_URL` и `HA_TOKEN` в `pi/.env`.

Таймеры через tool `set_timer` ставятся внутри `jarvis-pi`: после срабатывания звук `timer.wav` крутится до `TIMER_RING_DURATION_SEC` (по умолчанию 5 минут); wake-фраза останавливает звонок и проигрывает `decline.wav` без приёма команды.

Автозапуск при загрузке и перезапуск после падения (user systemd + linger). Перед стартом USB-карта из `ARECORD_DEVICE` становится дефолтной; микрофон 45%, выход 50% (`MIC_BOOT_PERCENT`, `SPEAKER_BOOT_PERCENT` в `.env`):

```bash
cd pi
chmod +x install-service.sh set-usb-audio.sh
./install-service.sh
```

Снять: `./install-service.sh --uninstall`

## Яндекс Станция

Отдельная Станция 1-го поколения: YNDX-0001, плата tulip-d1, Android 6.0.1, quasar 3.21, прошивка 2.369.5.46. Она в локальной сети, root и SSH уже есть. `reboot` и `poweroff` на этой модели не вызывать: такой сброс может повесить плату до выдёргивания из розетки.

Исходник прокси: `deepseek-bridge/bridge.py` и `deepseek-bridge/start.sh`. На колонке каталог `/data/quasar/deepseek-bridge/`. Python из Entware: `/opt/bin/python3`. `start.sh` не поднимает второй процесс, если pid в `bridge.pid` жив. Лог — `bridge.log`. Сертификаты: `SSL_CERT_FILE=/opt/etc/ssl/certs/ca-certificates.crt`. Автозапуск дописан в `/data/quasar/alicebridge/freeze-start.sh`. Обновления прошивки по-прежнему замораживает `freeze-updatesd.sh`; не отключать его и не убирать его вызов.

В `/system/vendor/quasar/quasar.cfg` у `aliced` стоят `uniProxyUrl=ws://127.0.0.1:8443/uni.ws` и пустой `uniProxyQuicUrl`. Копия конфига до правки: `/data/quasar/quasar.cfg.orig`. Отдельного URL генерации в `quasar.cfg` нет: распознавание и ответ идут одним WebSocket. Прокси слушает `127.0.0.1:8443` (`BRIDGE_LISTEN`, `BRIDGE_PORT`) и сам открывает `wss://uniproxy.alice.yandex.net/uni.ws`.

Ключ лежит в `deepseek-bridge/token` (на колонке путь задаёт `DEEPSEEK_TOKEN_FILE`, по умолчанию `/data/quasar/deepseek-bridge/token`). Файл в `.gitignore`. Содержимое ключа никуда не копировать.

Поведение — в `bridge.py` и `deepseek-bridge/agent/`. Режим `BRIDGE_MODE` по умолчанию `hybrid`. Кадры protobuf с префиксом `AAPI`. У голосового запроса выставляется `WaitClientApproval`, чтобы Яндекс не отвечал сам, пока прокси не решит. Финальный `AsrResult` с пустым текстом или с подстрокой из `YANDEX_HINTS` (музыка, громкость, таймер, будильник, пауза, блютус и соседние формулировки вроде «поставь», «стоп») отпускается в Яндекс. «Включи» и «выключи» перехватывает прокси. Остальной текст отменяется: ответ пишет агент в `deepseek-bridge/agent/`, колонке возвращается `AliceResponse`, звук запрашивается у Яндекса через `TtsGenerate`. Wake-фразы, распознавание и синтез прокси не делает.

Агент ходит в Chat Completions (`https://api.deepseek.com/chat/completions`, модель `BRIDGE_MODEL`, по умолчанию `deepseek-chat`) со своими tools. Включены погода, поиск, расчёт `run_python`, память, характер (`rewrite_self`, `reset_self`), `decline`, а также умный дом `get_home` и `control_home` (`HA_URL`, `HA_TOKEN` в окружении прокси). Если tool падает, текст ошибки уходит обратно в модель, и колонка озвучивает её пересказ. Таймер и громкость скопированы, но в конфиге выключены (`BRIDGE_TOOL_SET_TIMER`, `BRIDGE_TOOL_SET_SPEAKER_VOLUME`, `BRIDGE_TOOL_SET_MIC_VOLUME`), чтобы не перехватывать то, что колонка уже умеет. Пока флаг выключен, модель эти tools не видит. Даже если флаг включить, фразы из `YANDEX_HINTS` по-прежнему уходят в Яндекс. Значение `BRIDGE_MODE`, отличное от `hybrid`, пропускает кадры в Яндекс без DeepSeek. Это обход, пока прокси ещё стоит в `uniProxyUrl`, а не возврат штатного конфига.

Память и самоправки характера пишутся в `deepseek-bridge/data/` (на колонке это `/data/quasar/deepseek-bridge/data/`). Каталог в `.gitignore`.

Проверка без сети и без ключа (ожидается строка `selftest ok`):

```bash
python3 deepseek-bridge/bridge.py selftest
```

### Откат на штатный uniproxy

Если прокси ломает голос, вернуть конфиг из копии и остановить процесс прокси. `reboot` и `poweroff` не использовать. `freeze-updatesd.sh` не отключать.

1. Остановить только процесс прокси. Pid — в `/data/quasar/deepseek-bridge/bridge.pid`.
2. Вернуть `/system/vendor/quasar/quasar.cfg` из `/data/quasar/quasar.cfg.orig`. Штатных значений `uniProxyUrl` и `uniProxyQuicUrl` в репозитории нет, они только в этой копии.
3. Убрать из `/data/quasar/alicebridge/freeze-start.sh` только дописанный запуск `deepseek-bridge`. Вызов `freeze-updatesd.sh` оставить.
4. Команды, которой `aliced` перечитывает `quasar.cfg`, в репозитории нет. Не заменять её на `reboot` или `poweroff`.

Пока `uniProxyUrl` смотрит на `127.0.0.1:8443`, остановленный прокси оставляет колонку без голоса.

## Проверки

После правки Python на Pi, из каталога `pi`:

```bash
cd pi
PYTHONPATH=. python -m pytest
```

На Windows тесты на `unittest`, из каталога `windows`:

```bash
cd windows
python -m unittest discover -s tests
```

После правки прокси — `python3 deepseek-bridge/bridge.py selftest`.
