"""Pi edge service entrypoint."""

from __future__ import annotations

import logging
import queue
import random
import threading
import time
from datetime import datetime
from pathlib import Path

from jarvis_pi.audio_io import PcmCapture, play_pcm
from jarvis_pi.commands import dispatch_command, list_supported_triggers
from jarvis_pi.commands import think
from jarvis_pi.config import load_config
from jarvis_pi.wake import WakeStateMachine, normalize_text
from jarvis_pi.windows_client import WindowsClient

LOGGER = logging.getLogger("jarvis_pi")
WAKE_REPLIES = ("Да-да.", "Слушаю.", "Я тут.")
TIMEOUT_REPLY = "Дальше чиллить буду, пока."
STT_LOG_PATH = Path("log.txt")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    client = WindowsClient(config.windows_host, config.pcm_port, config.control_port)
    client.connect()

    wake_machine = WakeStateMachine(config.wake_words, config.command_window_sec)
    state_lock = threading.Lock()
    capture = PcmCapture(config.arecord_device, config.sample_rate)
    action_queue: queue.Queue[str] = queue.Queue()

    def speak(text: str) -> None:
        text = text.strip()
        if not text:
            return
        client.uplink_enabled.clear()
        try:
            with state_lock:
                wake_machine.reset()
            audio, sample_rate = client.request_speak(text)
            play_pcm(config.aplay_device, audio, sample_rate)
        finally:
            client.uplink_enabled.set()

    def on_command(command_text: str) -> None:
        dispatch_result = dispatch_command(command_text)
        if not dispatch_result:
            LOGGER.info("Unknown command fallback to think: %s", command_text)

            def fallback_stream_sentence(sentence: str) -> None:
                speak(sentence)

            speak(think.get_fallback_resolve_phrase())
            fallback_result = think.handle(command_text, fallback_stream_sentence)
            if not fallback_result.spoken_during_handle:
                speak(fallback_result.reply)
            return

        speak(dispatch_result.resolve_phrase)

        def stream_sentence(sentence: str) -> None:
            speak(sentence)

        execution_result = dispatch_result.handler(dispatch_result.payload, stream_sentence)
        if not execution_result.spoken_during_handle:
            speak(execution_result.reply)

    def worker_loop() -> None:
        while True:
            action = action_queue.get()
            if action == "__wake__":
                speak(random.choice(WAKE_REPLIES))
            elif action == "__timeout__":
                speak(TIMEOUT_REPLY)
            else:
                on_command(action)

    def handle_stt_message(message: dict) -> None:
        msg_type = message.get("type")
        if msg_type not in {"partial", "final"}:
            return
        text = normalize_text(str(message.get("text", "")))
        if not text:
            return
        is_final = msg_type == "final"
        if is_final:
            timestamp = datetime.now().strftime("%y.%m.%d %H:%M:%S")
            with STT_LOG_PATH.open("a", encoding="utf-8") as log_file:
                log_file.write(f"{timestamp} : {text}\n")

        with state_lock:
            if wake_machine.check_timeout():
                action_queue.put("__timeout__")

            command, woke_now, timed_out = wake_machine.process(text, is_final=is_final)
            if timed_out:
                action_queue.put("__timeout__")
                return
            if woke_now:
                action_queue.put("__wake__")
            if command:
                action_queue.put(command)

    threading.Thread(target=worker_loop, daemon=True).start()
    client.start_control_reader(handle_stt_message)
    capture.start(client.pcm_write_sink())

    LOGGER.info("Wake words: %s", ", ".join(config.wake_words))
    LOGGER.info("Supported commands: %s", ", ".join(list_supported_triggers()))
    LOGGER.info("Connected to Windows %s", config.windows_host)

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        LOGGER.info("Stopping...")
    finally:
        capture.stop()
        client.close()


if __name__ == "__main__":
    main()
