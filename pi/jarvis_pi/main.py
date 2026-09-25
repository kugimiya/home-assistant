"""Pi edge service entrypoint."""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from jarvis_pi.audio_io import PcmCapture, play_pcm, play_wav
from jarvis_pi.commands import think
from jarvis_pi.config import load_config
from jarvis_pi.sounds_paths import accept_wav, decline_wav, networking_wav
from jarvis_pi.wake import WakeStateMachine, normalize_text
from jarvis_pi.windows_client import WindowsClient

LOGGER = logging.getLogger("jarvis_pi")
STT_LOG_PATH = Path("log.txt")
STT_POST_TTS_GRACE_SEC = 0.7
POST_COMMAND_RELISTEN_DELAY_SEC = 1.0


def _preview(text: str, limit: int = 160) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    client = WindowsClient(config.windows_host, config.pcm_port, config.control_port)
    client.connect()

    wake_machine = WakeStateMachine(config.wake_words, config.command_window_sec)
    state_lock = threading.Lock()
    capture = PcmCapture(config.arecord_device, config.sample_rate)
    action_queue: queue.Queue[str] = queue.Queue()
    stt_suppress_until = 0.0

    def _playback_guard(*, reset_wake: bool) -> None:
        nonlocal stt_suppress_until
        stt_suppress_until = time.monotonic() + 3600.0
        client.uplink_enabled.clear()
        client.send_stt_reset()
        if reset_wake:
            with state_lock:
                wake_machine.reset()

    def _playback_release() -> None:
        nonlocal stt_suppress_until
        client.uplink_enabled.set()
        stt_suppress_until = time.monotonic() + STT_POST_TTS_GRACE_SEC

    def play_local_wav(path: Path, *, reset_wake: bool = True) -> None:
        if not path.is_file():
            LOGGER.error("Sound file missing: %s", path)
            return
        LOGGER.info("Local WAV -> %s", path.name)
        _playback_guard(reset_wake=reset_wake)
        try:
            play_wav(config.aplay_device, path)
            LOGGER.info("Local WAV playback done")
        finally:
            _playback_release()

    def speak(text: str, *, reset_wake: bool = True) -> None:
        text = text.strip()
        if not text:
            return
        LOGGER.info("TTS -> %s", _preview(text))
        _playback_guard(reset_wake=reset_wake)
        try:
            audio, sample_rate = client.request_speak(text)
            LOGGER.info("TTS received %d bytes @ %d Hz, playing...", len(audio), sample_rate)
            play_pcm(config.aplay_device, audio, sample_rate)
            LOGGER.info("TTS playback done")
        finally:
            _playback_release()

    def relisten_after_command() -> None:
        time.sleep(POST_COMMAND_RELISTEN_DELAY_SEC)
        with state_lock:
            wake_machine.arm_listening()
        LOGGER.info("Follow-up listening -> accept.wav")
        play_local_wav(accept_wav(), reset_wake=False)

    def on_command(command_text: str) -> None:
        LOGGER.info("User request: %s", _preview(command_text))

        def stream_sentence(sentence: str) -> None:
            LOGGER.info("Agent stream sentence: %s", _preview(sentence))
            speak(sentence)

        LOGGER.info("DeepSeek request -> networking.wav")
        play_local_wav(networking_wav())
        result = think.handle(command_text, stream_sentence)
        LOGGER.info("Agent reply: %s", _preview(result.reply))
        if result.end_session:
            LOGGER.info("Decline tool -> decline.wav")
            play_local_wav(decline_wav())
            return
        if not result.spoken_during_handle:
            speak(result.reply)
        relisten_after_command()

    def worker_loop() -> None:
        while True:
            action = action_queue.get()
            if action == "__wake__":
                LOGGER.info("Wake phrase detected -> accept.wav")
                play_local_wav(accept_wav(), reset_wake=False)
            elif action == "__timeout__":
                LOGGER.info("Command window timed out -> decline.wav")
                play_local_wav(decline_wav())
            else:
                LOGGER.info("Processing command: %s", _preview(action))
                on_command(action)

    def handle_stt_message(message: dict) -> None:
        if time.monotonic() < stt_suppress_until:
            return

        msg_type = message.get("type")
        if msg_type in {"hello", "ready", "audio"}:
            return
        if msg_type not in {"partial", "final"}:
            return
        text = normalize_text(str(message.get("text", "")))
        if not text:
            return
        is_final = msg_type == "final"
        if is_final:
            LOGGER.info("STT final: %s", _preview(text))
            timestamp = datetime.now().strftime("%y.%m.%d %H:%M:%S")
            with STT_LOG_PATH.open("a", encoding="utf-8") as log_file:
                log_file.write(f"{timestamp} : {text}\n")
        else:
            LOGGER.debug("STT partial: %s", _preview(text))

        with state_lock:
            command, woke_now, timed_out = wake_machine.process(text, is_final=is_final)
            if timed_out:
                LOGGER.info("Command window expired on phrase: %s", _preview(text))
                action_queue.put("__timeout__")
                return
            if woke_now:
                LOGGER.info("Wake phrase matched in: %s", _preview(text))
                action_queue.put("__wake__")
            if command:
                LOGGER.info("Command queued: %s", _preview(command))
                action_queue.put(command)

    threading.Thread(target=worker_loop, daemon=True).start()
    client.start_control_reader(handle_stt_message)
    capture.start(client.pcm_write_sink())

    LOGGER.info("Wake words: %s", ", ".join(config.wake_words))
    LOGGER.info("Connected to Windows %s", config.windows_host)
    LOGGER.info("Assistant is listening...")

    try:
        while True:
            time.sleep(0.25)
            with state_lock:
                if wake_machine.check_timeout():
                    LOGGER.info("Command window expired (silence)")
                    action_queue.put("__timeout__")
    except KeyboardInterrupt:
        LOGGER.info("Stopping...")
    finally:
        capture.stop()
        client.close()


if __name__ == "__main__":
    main()
