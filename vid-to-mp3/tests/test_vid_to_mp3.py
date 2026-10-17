import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from vid_to_mp3 import convert, main  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def make_video(path: Path, *, audio: bool) -> Path:
    """A 1 s test video, with a 440 Hz tone if audio is True."""
    cmd = ["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1"]
    cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=1"] if audio else []
    subprocess.run(cmd + ["-pix_fmt", "yuv420p", str(path)], check=True)
    return path


def streams(path: Path) -> list[dict]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"]


def test_output_is_audio_only_mp3_with_the_source_duration(tmp_path):
    video = make_video(tmp_path / "IMG 0001.MOV", audio=True)  # a space, as in real file names
    mp3 = convert(video)
    (stream,) = streams(mp3)
    assert (mp3.name, stream["codec_name"]) == ("IMG 0001.mp3", "mp3")
    assert float(stream["duration"]) == pytest.approx(1.0, abs=0.1)


def test_existing_output_is_kept_and_a_silent_video_is_reported(tmp_path, capsys):
    with_audio = make_video(tmp_path / "a.mov", audio=True)
    silent = make_video(tmp_path / "b.mov", audio=False)
    convert(with_audio)
    marker = (tmp_path / "a.mp3").stat().st_mtime_ns

    assert main([str(with_audio), str(silent)]) == 1  # one failure must not stop the batch
    assert (tmp_path / "a.mp3").stat().st_mtime_ns == marker
    assert not (tmp_path / "b.mp3").exists()
    assert "a.mp3" in capsys.readouterr().err
