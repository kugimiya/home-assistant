# Home assistant (Pi + Windows)

Два Python-сервиса:

- `pi/` — Raspberry Pi: микрофон, колонки, wake-фразы и команды.
- `windows/` — Windows: распознавание Vosk и синтез Piper.

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

Во время ответа TTS микрофон остаётся включённым (AEC по reference из колонки). Wake-фразу по-прежнему распознаёт Windows STT: она прерывает озвучку, играет `accept.wav` и открывает окно команды. На Pi отдельная модель Vosk не нужна. `AEC_BACKEND=off` отключает WebRTC AEC. Задержку эха задаёт `AEC_STREAM_DELAY_MS`.

Таймеры через tool `set_timer` ставятся внутри `jarvis-pi`: после срабатывания звук `timer.wav` крутится до `TIMER_RING_DURATION_SEC` (по умолчанию 5 минут); wake-фраза останавливает звонок и проигрывает `decline.wav` без приёма команды.

Автозапуск при загрузке и перезапуск после падения (user systemd + linger). Перед стартом USB-карта из `ARECORD_DEVICE` становится дефолтной; микрофон 45%, выход 25% (`MIC_BOOT_PERCENT`, `SPEAKER_BOOT_PERCENT` в `.env`):

```bash
cd pi
chmod +x install-service.sh set-usb-audio.sh
./install-service.sh
```

Снять: `./install-service.sh --uninstall`
