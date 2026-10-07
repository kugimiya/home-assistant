"""Pi edge service entrypoint."""

from __future__ import annotations

import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

from jarvis_pi.aec import build_echo_canceller
from jarvis_pi.audio_engine import AudioEngine
from jarvis_pi.barge_in import BargeInDetector
from jarvis_pi.commands import think
from jarvis_pi.commands import timer as timer_commands
from jarvis_pi.config import load_config
from jarvis_pi.memory import get_memory_manager
from jarvis_pi.resample import resample_s16_mono
from jarvis_pi.sounds_paths import accept_wav, decline_wav, networking_wav, timer_wav
from jarvis_pi.timer_service import TimerService
from jarvis_pi.wake import WakeStateMachine, normalize_text
from jarvis_pi.windows_client import WindowsClient

LOGGER = logging.getLogger("jarvis_pi")
STT_LOG_PATH = Path("log.txt")
STT_POST_TTS_GRACE_SEC = 0.7
POST_COMMAND_RELISTEN_DELAY_SEC = 1.0


def _modules_needing_reload(health: dict) -> list[str]:
    reload: list[str] = []
    for name in ("stt", "tts"):
        state = health.get(name, {}).get("state")
        if state != "ready":
            reload.append(name)
    return reload


def ensure_windows_modules(client: WindowsClient) -> None:
    """Health check and reload STT/TTS on Windows when not ready."""
    try:
        health = client.request_health()
    except (OSError, TimeoutError) as exc:
        LOGGER.warning("Windows health check failed: %s", exc)
        if not client.reconnect(reason="health check"):
            return
        try:
            health = client.request_health()
        except (OSError, TimeoutError) as retry_exc:
            LOGGER.warning("Windows health check failed after reconnect: %s", retry_exc)
            return

    modules = _modules_needing_reload(health)
    if not modules:
        LOGGER.debug("Windows health ok (stt=%s, tts=%s)", health.get("stt"), health.get("tts"))
        return

    LOGGER.info("Windows modules not ready (%s), reloading: %s", health, modules)
    try:
        result = client.request_reload(modules)
        LOGGER.info("Windows reload finished: %s", result)
    except (OSError, TimeoutError) as exc:
        LOGGER.warning("Windows reload failed: %s", exc)


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
    speaking = False
    barge_abort = False
    action_queue: queue.Queue[str] = queue.Queue()
    stt_suppress_until = 0.0
    pending_command: str | None = None
    pending_command_timer: threading.Timer | None = None
    pending_command_lock = threading.Lock()

    def cancel_pending_command() -> None:
        nonlocal pending_command, pending_command_timer
        with pending_command_lock:
            pending_command = None
            if pending_command_timer is not None:
                pending_command_timer.cancel()
                pending_command_timer = None

    def _arm_commit_timer(text: str) -> None:
        """Start/restart the debounce timer for a pending command text."""
        nonlocal pending_command, pending_command_timer

        def commit() -> None:
            with pending_command_lock:
                if pending_command != text:
                    return
                pending_command_local = text
            # Stop listening only when the command is actually handed to the worker.
            with state_lock:
                wake_machine.reset()
            action_queue.put(pending_command_local)
            cancel_pending_command()
            LOGGER.info("STT final committed -> queue: %s", _preview(pending_command_local))

        with pending_command_lock:
            pending_command = text
            if pending_command_timer is not None:
                pending_command_timer.cancel()
            delay = config.stt_command_commit_sec
            pending_command_timer = threading.Timer(delay, commit)
            pending_command_timer.daemon = True
            pending_command_timer.start()

    def schedule_command(text: str) -> None:
        text = text.strip()
        if not text:
            return
        with pending_command_lock:
            previous = pending_command
        if previous and previous != text:
            # Another final while still debouncing: keep both (Vosk often splits one speech).
            if text in previous:
                merged = previous
            elif previous in text:
                merged = text
            else:
                merged = f"{previous} {text}".strip()
            if merged != text:
                LOGGER.info(
                    "STT final merged into pending (%d -> %d chars)",
                    len(previous),
                    len(merged),
                )
            text = merged
        _arm_commit_timer(text)
        LOGGER.info(
            "STT final scheduled (commit in %.1fs unless speech continues): %s",
            config.stt_command_commit_sec,
            _preview(text),
        )

    def bump_pending_commit_on_partial() -> None:
        """Speech continued after a final: keep text, restart commit delay."""
        with pending_command_lock:
            text = pending_command
        if not text:
            return
        _arm_commit_timer(text)
        LOGGER.info(
            "STT commit delayed (speech continues), still pending: %s",
            _preview(text),
        )

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

    def play_local_wav(path: Path, *, reset_wake: bool = True, mute_uplink: bool = True) -> None:
        if not path.is_file():
            LOGGER.error("Sound file missing: %s", path)
            return
        LOGGER.info("Local WAV -> %s", path.name)
        if mute_uplink:
            _playback_guard(reset_wake=reset_wake)
        elif reset_wake:
            with state_lock:
                wake_machine.reset()
        try:
            audio_engine.play_wav(path)
            LOGGER.info("Local WAV playback done")
        finally:
            if mute_uplink:
                _playback_release()

    def speak(text: str, *, duplex: bool = True) -> bool:
        """Speak text. Return False when barge-in interrupted playback."""
        nonlocal speaking
        text = text.strip()
        if not text:
            return True
        LOGGER.info("TTS -> %s", _preview(text))
        audio, sample_rate = client.request_speak(text)
        pcm = resample_s16_mono(audio, sample_rate, 16000)
        LOGGER.info("TTS received %d bytes @ %d Hz", len(audio), sample_rate)
        if duplex:
            speaking = True
            barge_in.set_enabled(True)
            try:
                finished = audio_engine.play_pcm(pcm, text=text)
            finally:
                barge_in.set_enabled(False)
                speaking = False
            LOGGER.info("TTS playback done (finished=%s)", finished)
            return finished
        _playback_guard(reset_wake=True)
        try:
            audio_engine.play_pcm(pcm, text=text)
        finally:
            _playback_release()
        return True

    def finish_barge_in() -> None:
        LOGGER.info("Barge-in -> accept.wav")
        play_local_wav(accept_wav(), reset_wake=False)
        with state_lock:
            wake_machine.arm_listening()

    def relisten_after_command() -> None:
        time.sleep(POST_COMMAND_RELISTEN_DELAY_SEC)
        with state_lock:
            wake_machine.arm_listening()
        LOGGER.info("Follow-up listening -> accept.wav")
        play_local_wav(accept_wav(), reset_wake=False)

    def on_command(command_text: str) -> None:
        LOGGER.info("User request: %s", _preview(command_text))

        def stream_sentence(sentence: str) -> None:
            nonlocal barge_abort
            if barge_abort:
                return
            LOGGER.info("Agent stream sentence: %s", _preview(sentence))
            if not speak(sentence):
                barge_abort = True

        LOGGER.info("DeepSeek request -> networking.wav")
        play_local_wav(networking_wav())
        barge_abort = False
        result = think.handle(command_text, stream_sentence)
        LOGGER.info("Agent reply: %s", _preview(result.reply))
        if barge_abort:
            finish_barge_in()
            return
        if result.end_session:
            LOGGER.info("Decline tool -> decline.wav")
            play_local_wav(decline_wav())
            return
        if not result.spoken_during_handle:
            if not speak(result.reply):
                finish_barge_in()
                return
        if result.await_followup:
            relisten_after_command()
        else:
            LOGGER.info("Task complete — not arming follow-up listen (wake phrase required)")

    def worker_loop() -> None:
        while True:
            action = action_queue.get()
            if action == "__wake__":
                LOGGER.info("Wake phrase detected -> accept.wav")
                play_local_wav(accept_wav(), reset_wake=False)
            elif action == "__timeout__":
                LOGGER.info("Command window timed out -> decline.wav")
                play_local_wav(decline_wav())
            elif action == "__timer_dismiss__":
                LOGGER.info("Timer dismissed via wake -> decline.wav")
                play_local_wav(decline_wav())
            else:
                LOGGER.info("Processing command: %s", _preview(action))
                on_command(action)

    def handle_stt_message(message: dict) -> None:
        msg_type = message.get("type")
        if msg_type in {"hello", "ready", "audio", "health", "reload_result"}:
            return
        if msg_type == "error":
            LOGGER.warning("Windows error event: %s", message)
            return
        if msg_type not in {"partial", "final"}:
            return
        text = normalize_text(str(message.get("text", "")))
        if not text:
            return
        is_final = msg_type == "final"

        if speaking:
            barge_in.consider(text, is_final=is_final)
            return

        if timer_service.is_ringing():
            if timer_service.wake_dismisses_ring(text, is_final=is_final):
                LOGGER.info("Wake during timer ring -> stop alarm")
                timer_service.stop_ringing()
                cancel_pending_command()
                with state_lock:
                    wake_machine.reset()
                action_queue.put("__timer_dismiss__")
            return

        if time.monotonic() < stt_suppress_until:
            return
        if is_final:
            LOGGER.info("STT final: %s", _preview(text))
            timestamp = datetime.now().strftime("%y.%m.%d %H:%M:%S")
            with STT_LOG_PATH.open("a", encoding="utf-8") as log_file:
                log_file.write(f"{timestamp} : {text}\n")
        else:
            LOGGER.debug("STT partial: %s", _preview(text))

        if not is_final:
            # Do NOT cancel a scheduled final on partial — user often keeps talking
            # after Vosk's first endpointer final. Just push the commit deadline.
            bump_pending_commit_on_partial()

        with state_lock:
            command, woke_now, timed_out = wake_machine.process(text, is_final=is_final)
            if timed_out:
                LOGGER.info("Command window expired on phrase: %s", _preview(text))
                cancel_pending_command()
                action_queue.put("__timeout__")
                return
            if woke_now:
                LOGGER.info("Wake phrase matched in: %s", _preview(text))
                action_queue.put("__wake__")
            if command:
                LOGGER.info("Command detected: %s", _preview(command))
                schedule_command(command)

    def health_monitor_loop() -> None:
        interval = config.windows_health_interval_sec
        while True:
            time.sleep(interval)
            ensure_windows_modules(client)

    def on_barge_trigger() -> None:
        nonlocal barge_abort
        barge_abort = True
        audio_engine.stop_playback()
        client.send_stt_reset()

    timer_service = TimerService(
        aplay_device=config.aplay_device,
        timer_sound=timer_wav(),
        wake_words=config.wake_words,
    )
    audio_engine = AudioEngine(
        input_device=config.arecord_device,
        output_device=config.aplay_device,
        canceller=build_echo_canceller(),
        uplink_write=client.pcm_write_sink().write,
    )
    barge_in = BargeInDetector(
        wake_words=config.wake_words,
        timeline=audio_engine.timeline,
        on_trigger=on_barge_trigger,
    )
    audio_engine.on_clean_frame = barge_in.feed
    timer_service.engine = audio_engine
    timer_commands.configure(timer_service)

    threading.Thread(target=worker_loop, daemon=True).start()
    client.start_control_reader(handle_stt_message)
    ensure_windows_modules(client)
    threading.Thread(target=health_monitor_loop, daemon=True).start()
    audio_engine.start()

    LOGGER.info("Wake words: %s", ", ".join(config.wake_words))
    LOGGER.info("Connected to Windows %s", config.windows_host)
    LOGGER.info("Assistant is listening...")

    try:
        while True:
            time.sleep(0.25)
            with state_lock:
                if wake_machine.check_timeout():
                    LOGGER.info("Command window expired (silence)")
                    cancel_pending_command()
                    action_queue.put("__timeout__")
    except KeyboardInterrupt:
        LOGGER.info("Stopping...")
    finally:
        cancel_pending_command()
        get_memory_manager().shutdown()
        audio_engine.stop()
        client.close()


if __name__ == "__main__":
    main()
