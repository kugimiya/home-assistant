"""Windows audio service entrypoint."""

from __future__ import annotations

import logging

from jarvis_win.config import load_config
from jarvis_win.server import AudioService


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    AudioService(config).run()


if __name__ == "__main__":
    main()
