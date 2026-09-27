"""ALSA volume tools."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from jarvis_pi.commands.volume import mixer_device, set_mic_volume, set_speaker_volume


def test_mixer_device_strips_pcm_plugin() -> None:
    assert mixer_device("plughw:Device,0") == "hw:Device"
    assert mixer_device("hw:1,0") == "hw:1"
    assert mixer_device("default") == "default"


def test_set_speaker_volume_rejects_out_of_range() -> None:
    assert "0 до 100" in set_speaker_volume(101)
    assert "0 до 100" in set_speaker_volume(-1)
    assert "целым" in set_speaker_volume(50.5)


def test_set_speaker_volume_calls_amixer() -> None:
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with (
        patch("jarvis_pi.commands.volume.shutil.which", return_value="/usr/bin/amixer"),
        patch.dict("os.environ", {"APLAY_DEVICE": "plughw:Device,0"}, clear=False),
        patch("jarvis_pi.commands.volume.subprocess.run", return_value=completed) as run,
    ):
        result = set_speaker_volume(40)

    assert "40" in result
    run.assert_called_once()
    cmd = run.call_args.args[0]
    assert cmd == ["amixer", "-D", "hw:Device", "sset", "Speaker", "40%"]


def test_set_mic_volume_uses_arecord_device() -> None:
    completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
    with (
        patch("jarvis_pi.commands.volume.shutil.which", return_value="/usr/bin/amixer"),
        patch.dict("os.environ", {"ARECORD_DEVICE": "plughw:Mic,0", "MIC_ALSA_CONTROL": "Mic"}, clear=False),
        patch("jarvis_pi.commands.volume.subprocess.run", return_value=completed) as run,
    ):
        result = set_mic_volume("15")

    assert "15" in result
    cmd = run.call_args.args[0]
    assert cmd == ["amixer", "-D", "hw:Mic", "sset", "Mic", "15%"]
