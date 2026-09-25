# Home assistant (Pi + Windows)

Два Python-сервиса:

- `pi/` — Raspberry Pi: микрофон, колонки, wake-фразы и команды.
- `windows/` — Windows: распознавание Vosk и синтез Piper.

## Windows

```powershell
cd windows
.\install.ps1
.\.venv\Scripts\python.exe -m jarvis_win
```

Откройте в брандмауэре TCP `9700` и `9701` для IP платы.

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
