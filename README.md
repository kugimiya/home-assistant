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

Откройте в брандмауэре TCP `9700` и `9701` для IP платы.

Python-пакет **vosk 0.3.50** собирается локально через Docker (`install-vosk.ps1`), не с PyPI: у тега `v0.3.50` на GitHub нет `win_amd64.whl`. Нужен **Docker Desktop** (Linux containers); первая сборка Kaldi/MinGW может занять часы. Повторный `fix.ps1` ставит кэш из `third_party/vosk-api/wheelhouse`. Пересобрать: `VOSK_FORCE_REBUILD=1`.

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

Таймеры через tool `set_timer` используют `at`/`atd` на Pi:

```bash
sudo apt install at
sudo systemctl enable --now atd
```
