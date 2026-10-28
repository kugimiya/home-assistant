# Home assistant (Jarvis)

Голосовой ассистент Jarvis. В репозитории три части, и это разные процессы:

- `pi/` — Raspberry Pi: микрофон, колонки, wake-фразы, команды, tools и клиент DeepSeek.
- `windows/` — Windows: распознавание Vosk и синтез Piper. Своей логики команд нет.
- `deepseek-bridge/` — прокси для отдельной Яндекс Станции. К Pi и к `windows/` не подключается.

Клиент DeepSeek на Pi и прокси колонки не делят ключ, URL и модель. У прокси свой `BRIDGE_MODEL` и файл `token`. Менять одну сторону по образцу другой нельзя.

## Поток на Pi

Микрофон читает `AudioEngine` (`ARECORD_DEVICE`, по умолчанию `plughw:Device,0`, `SAMPLE_RATE` 16000). Кадры уходят на Windows по PCM-сокету. Отдельной модели Vosk на Pi нет.

Windows отвечает по control-каналу событиями `partial` и `final`. Машина состояний `WakeStateMachine` ждёт wake-фразу (`WAKE_WORDS`, по умолчанию `компьютер`, `джарвис`, `прослушка`) и затем окно команды (`COMMAND_WINDOW_SEC`, по умолчанию 10 с). Финальный текст коммитится после паузы `STT_COMMAND_COMMIT_SEC` (по умолчанию 1 с); следующий `partial` отодвигает коммит. Совпавшая команда попадает в очередь и уходит в `jarvis_pi.commands.think.handle`.

`think` ходит в DeepSeek Responses API (`DEEPSEEK_RESPONSES_URL`, по умолчанию `https://api.deepseek.com/responses`; модель `DEEPSEEK_MODEL`, по умолчанию `deepseek-flash`; ключ `DEEPSEEK_API_KEY` в `pi/.env`). Ответ стримится. Законченные предложения озвучиваются по ходу. Текст запроса `speak` уходит на Windows, Piper возвращает PCM в том же control-канале, Pi приводит его к 16000 Гц и играет в `APLAY_DEVICE`.

Пока идёт TTS, микрофон остаётся включённым. Эхо снимает AEC (`AEC_BACKEND`, по умолчанию `webrtc`; `off` выключает; задержка `AEC_STREAM_DELAY_MS`, по умолчанию 80). Wake-фразу по-прежнему распознаёт Windows STT: она обрывает озвучку, играет `accept.wav` и открывает окно команды. Перед запросом в DeepSeek играет `networking.wav`. Tool `decline` и таймаут окна играют `decline.wav`.

Tools в `think`: `get_weather`, `web_search`, `set_timer`, `set_speaker_volume`, `set_mic_volume`, `get_home`, `control_home`, `run_python`, `decline`, `search_memory`, `add_memory`, `get_profile`, `get_recent_episodes`, `list_memory`, `memory_crud`, `rewrite_self`, `reset_self`.

Свет и прочие устройства Home Assistant — `get_home` и `control_home`. Адрес и долгоживущий токен: `HA_URL` (по умолчанию `http://127.0.0.1`) и `HA_TOKEN` в `pi/.env`. Таймер `set_timer` живёт внутри процесса `jarvis-pi`: после срабатывания `timer.wav` крутится `TIMER_RING_DURATION_SEC` секунд (по умолчанию 300). Wake-фраза во время звонка останавливает его и играет `decline.wav`, команду при этом не принимает.

Память — SQLite в `pi/data/` (`MEMORY_DB_PATH`, по умолчанию `pi/data/memory.db`). Каталог `pi/data/` в git не входит. Характер — женский род, голос Piper; константа в `pi/jarvis_pi/personality/prompt.py`.

Сообщения control-канала, JSON по строке:

- Pi → Windows: `hello`, `speak`, `stt_reset`, `health`, `reload_modules`.
- Windows → Pi: `ready`, `partial`, `final`, `audio`, `health`, `reload_result`, `error`.

PCM — отдельный TCP-сокет, сырые байты, не JSON.

## Запуск и починка

### Windows

Первичная установка (скачивает модели, при необходимости ставит Python через winget):

```powershell
cd windows
.\install.ps1
.\.venv\Scripts\python.exe -m jarvis_win
```

Починить venv и зависимости без переустановки Python: `.\fix.ps1` из `windows`. Из Git Bash: `./fix.sh`.

Автозапуск при загрузке и перезапуск после падения (Планировщик заданий; перезапуск не чаще раза в минуту): `.\install-service.ps1`. Снять: `.\install-service.ps1 -Uninstall`.

STT и TTS при старте процесса не грузятся. После подключения Pi шлёт `health` и при необходимости `reload_modules` (`stt`, `tts` или `all`). Тот же цикл на Pi каждые `WINDOWS_HEALTH_INTERVAL_SEC` (по умолчанию 600) из `pi/.env`. В `health` / `reload_result` поля `stt` и `tts` со `state`: `unloaded`, `loading`, `ready`, `error`. Синтез `speak` идёт в отдельном потоке. Таймаут синтеза: `PIPER_SYNTH_TIMEOUT_SEC` (по умолчанию 120). Probe при reload TTS: `PIPER_PROBE_TIMEOUT_SEC` (по умолчанию 30).

Пакет vosk 0.3.50 собирается локально через Docker (`install-vosk.ps1`, `Dockerfile.vosk-win`, `VOSK_GITHUB_REF=v0.3.50`), не с PyPI. Нужен Docker Desktop, Linux containers. Повторный `fix.ps1` берёт кэш из `third_party/vosk-api/wheelhouse`. Пересобрать: `VOSK_FORCE_REBUILD=1`.

Модели по умолчанию: Vosk `models/vosk-model-ru-0.42`, Piper `models/ru_RU-irina-medium.onnx` и `third_party/piper/piper.exe`. Каталоги `windows/models/` и `windows/third_party/` в git не входят.

### Raspberry Pi

```bash
cd pi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# укажите WINDOWS_HOST
PYTHONPATH=. python -m jarvis_pi
```

`WINDOWS_HOST` обязателен. Автозапуск (user systemd + linger): перед стартом USB-карта из `ARECORD_DEVICE` становится дефолтной, микрофон `MIC_BOOT_PERCENT` (45), выход `SPEAKER_BOOT_PERCENT` (50).

```bash
cd pi
chmod +x install-service.sh set-usb-audio.sh
./install-service.sh
```

Снять: `./install-service.sh --uninstall`.

Отдельного `fix`-скрипта на Pi нет. Зависимости ставятся из `pi/requirements.txt` в `pi/.venv`.

### Порты

| Кто слушает | Переменные | По умолчанию |
| --- | --- | --- |
| Windows, PCM | `PCM_LISTEN_HOST`, `PCM_LISTEN_PORT`; на Pi `PCM_PORT` | `0.0.0.0:9700` |
| Windows, control | `CONTROL_LISTEN_HOST`, `CONTROL_LISTEN_PORT`; на Pi `CONTROL_PORT` | `0.0.0.0:9701` |
| Прокси на колонке | `BRIDGE_LISTEN`, `BRIDGE_PORT` | `127.0.0.1:8443`, путь `/uni.ws` |

На Windows в брандмауэре открыть TCP `9700` и `9701` для IP платы. Образцы переменных: `pi/.env.example`, `windows/.env.example`. Рабочие `.env` не коммитить.

### Что не коммитить

Из `.gitignore`: `.env`, `creds.txt`, `deepseek-bridge/token`, `deepseek-bridge/data/`, `**/.venv/`, `**/__pycache__/`, `*.pyc`, `windows/models/`, `windows/third_party/`, `pi/data/`, `.DS_Store`, `.vscode`.

Ключи (`DEEPSEEK_API_KEY`, `HA_TOKEN`, файл `deepseek-bridge/token`) и пароли в репозиторий, в логи и в этот файл не копировать. Содержимое `token` не читать в ответ и не цитировать.

## deepseek-bridge

Те же заметки про колонку, что в `README.md`. Здесь — ограничения для правок.

Исходник в репозитории: `deepseek-bridge/bridge.py`, `deepseek-bridge/start.sh`. На колонке сервис лежит в `/data/quasar/deepseek-bridge/`. Интерпретатор — Python из Entware, `/opt/bin/python3` (шебанг `bridge.py` и вызов в `start.sh`). `start.sh` не поднимает второй процесс, если pid из `bridge.pid` жив. Лог: `bridge.log` (`BRIDGE_LOG`). Сертификаты: `SSL_CERT_FILE=/opt/etc/ssl/certs/ca-certificates.crt`. Автозапуск дописан в `/data/quasar/alicebridge/freeze-start.sh`.

Колонка — Яндекс Станция 1-го поколения (YNDX-0001, плата tulip-d1, Android 6.0.1, quasar 3.21, прошивка 2.369.5.46). Она в локальной сети, root и SSH уже есть. `reboot` и `poweroff` на этой модели не вызывать: такой сброс может повесить плату до выдёргивания из розетки. `freeze-updatesd.sh` по-прежнему замораживает обновления прошивки; не отключать его и не удалять его вызов.

В `/system/vendor/quasar/quasar.cfg` у `aliced` выставлены `uniProxyUrl=ws://127.0.0.1:8443/uni.ws` и пустой `uniProxyQuicUrl`. Копия конфига до правки: `/data/quasar/quasar.cfg.orig`. Отдельного URL генерации в `quasar.cfg` нет: распознавание и ответ идут одним WebSocket.

Поведение брать из `bridge.py`. Прокси принимает WebSocket колонки и сам открывает `wss://uniproxy.alice.yandex.net/uni.ws` (хост `uniproxy.alice.yandex.net`, порт 443). Кадры protobuf с префиксом `AAPI`. Режим `BRIDGE_MODE` по умолчанию `hybrid` (`start.sh` тоже подставляет `hybrid`). В любом другом режиме кадры уходят наверх и вниз как есть, без DeepSeek.

В `hybrid` голосовой запрос перед отправкой в Яндекс получает `WaitClientApproval` (поле по пути Event / VoiceInput / Request / UniproxyOptions). Пока прокси не решит, Яндекс сам не отвечает. `continue` для этого запроса удерживается. По финальному `AsrResult`:

- пустой текст или подстрока из `YANDEX_HINTS` (`музык`, `песн`, `трек`, `альбом`, `радио`, `громче`, `тише`, `громкост`, `таймер`, `будильник`, `следующ`, `предыдущ`, `пауза`, `паузу`, `продолж`, `моя волна`, `блютус`, `bluetooth`, `поставь`, `стоп`, `дальше`, `назад`) — запрос отпускается в Яндекс уже удержанным `continue` или собранным кадром continue. «Включи» и «выключи» в этот список не входят: свет и устройства уходят в `get_home` / `control_home`. «Включи музыку» всё равно попадает в Яндекс по подстроке `музык`;
- иначе запрос в Яндекс отменяется, текст уходит в агент `deepseek-bridge/agent/`, колонке вниз уходит `AliceResponse`, а звук запрашивается у Яндекса кадром `TtsGenerate`. Чужие `alice`/`tts` и их аудиопотоки для такого ответа отбрасываются.

Wake-фразы, STT и TTS в прокси нет: речь и озвучка остаются у Яндекса. Агент — Chat Completions, `https://api.deepseek.com/chat/completions`, модель `BRIDGE_MODEL` (по умолчанию `deepseek-chat`), tools, без стрима. Ключ читается из файла `DEEPSEEK_TOKEN_FILE` (на колонке `/data/quasar/deepseek-bridge/token`; в репозитории тот же относительный путь в `.gitignore`). В запросе `temperature` 0.6, `max_tokens` 800, таймаут 45 с на один ход. В историю реплик попадают последние 8 сообщений. Озвучиваемый текст обрезается до 500 символов. Ошибки 401/403, 429 и прочие превращаются в короткие фразы и тоже озвучиваются через тот же путь.

Включённые tools: `get_weather`, `web_search`, `run_python`, `decline`, память (`search_memory`, `add_memory`, `get_profile`, `get_recent_episodes`, `list_memory`, `memory_crud`), характер (`rewrite_self`, `reset_self`). Характер тот же по сухости и женскому роду, что на Pi. В тексте для колонки: раньше жила в самопальной колонке, сейчас в Яндекс Станции, озвучивает Яндекс, отзывается на Alice. В озвучке имя только латиницей Alice: кириллическое «Алиса» — wake-фраза, из-за неё ответ обрывается. Туда же зашиты пределы из `agent/config.py`: 800 токенов и 45 секунд на ход, 6 раундов tools, вслух не больше 500 символов. Инструкции собирает `agent/think.py` и не упоминает выключенные tools.

`get_home` и `control_home` включены. Адрес и токен Home Assistant на колонке: `HA_URL` и `HA_TOKEN` в окружении процесса прокси. Если tool бросает исключение, в следующий ход модели уходит текст `Ошибка инструмента …`, и озвучивается уже её пересказ, не сырой traceback.

Выключены по умолчанию, код на месте (`agent/config.py`, `STATION_TOOLS`): `set_timer`, `set_speaker_volume`, `set_mic_volume`. Включить конкретный tool: `BRIDGE_TOOL_<NAME>=1`. Пока флаг выключен, схема tool в запрос не попадает. «Таймер», «громче», «поставь» по-прежнему уходят в Яндекс через `YANDEX_HINTS`. Звонок таймера и wake для него не переносились.

Память SQLite и файлы характера — `deepseek-bridge/data/` (`MEMORY_DB_PATH`, на колонке каталог сервиса + `data/`). Каталог в `.gitignore`. Саммари сессии тоже ходит в Chat Completions этим же ключом, не в Responses API.

Это не клиент Pi. На Pi — Responses API, модель `deepseek-flash`, ключ `DEEPSEEK_API_KEY`, свой стрим в Piper. Общий `.env` у них нет. Модель прокси — `BRIDGE_MODEL`, не `DEEPSEEK_MODEL`.

## Откат колонки на штатный uniproxy

Если прокси ломает голос, конфиг колонки вернуть из копии, процесс прокси остановить. `reboot` и `poweroff` не использовать. `freeze-updatesd.sh` не отключать.

1. Остановить только процесс прокси. Pid — в `/data/quasar/deepseek-bridge/bridge.pid`. `start.sh` считает процесс живым, если `kill -0` по этому pid успешен; для остановки завершить этот pid. Второй экземпляр `start.sh` сам не поднимется, пока pid жив.
2. Вернуть `/system/vendor/quasar/quasar.cfg` из `/data/quasar/quasar.cfg.orig`. Штатных значений `uniProxyUrl` и `uniProxyQuicUrl` в репозитории нет, они только в этой копии.
3. Убрать из `/data/quasar/alicebridge/freeze-start.sh` только дописанный запуск `deepseek-bridge`. Вызов `freeze-updatesd.sh` оставить.
4. Команды, которой `aliced` перечитывает `quasar.cfg`, в репозитории нет. Не заменять её на `reboot` или `poweroff`.

Пока `uniProxyUrl` смотрит на `127.0.0.1:8443`, мёртвый прокси оставляет колонку без голоса. Временный обход, не откат конфига: `BRIDGE_MODE` со значением, отличным от `hybrid`, пропускает кадры в `uniproxy.alice.yandex.net` без DeepSeek. После настоящего отката этот обход не нужен.

Ключ в `token` при откате не печатать и не копировать.

## Проверки после правки Python

Pi, из каталога `pi` (pytest есть в `pi/requirements.txt`, тесты в `pi/tests/`):

```bash
cd pi
PYTHONPATH=. python -m pytest
```

Windows, из каталога `windows`. Тесты на `unittest` из стандартной библиотеки, зависимости pytest нет; модули сами добавляют `windows/` в `sys.path`:

```bash
cd windows
python -m unittest discover -s tests
```

`deepseek-bridge/bridge.py` гоняет selftest без сети и без ключа, если первый аргумент `selftest`:

```bash
python3 deepseek-bridge/bridge.py selftest
```

Ожидаемая строка: `selftest ok`. На колонке тот же файл запускает `/opt/bin/python3`.
