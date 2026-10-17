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
    mp3 = convert(video, tmp_path / "out")
    (stream,) = streams(mp3)
    assert (mp3.name, stream["codec_name"]) == ("IMG 0001.mp3", "mp3")
    assert float(stream["duration"]) == pytest.approx(1.0, abs=0.1)


def test_folder_run_converts_videos_into_the_subfolder_and_never_overwrites(tmp_path, capsys):
    make_video(tmp_path / "a.mov", audio=True)
    make_video(tmp_path / "b.MOV", audio=False)  # no sound: fails, but must not stop the batch
    (tmp_path / "notes.txt").write_text("not a video")

    assert main([str(tmp_path)]) == 1
    assert sorted(f.name for f in (tmp_path / "mp3").iterdir()) == ["a.mp3"]
    out = capsys.readouterr()
    assert "b.MOV" in out.err
    assert "notes.txt" not in out.out + out.err

    first = (tmp_path / "mp3" / "a.mp3").stat().st_mtime_ns
    main([str(tmp_path)])
    assert (tmp_path / "mp3" / "a.mp3").stat().st_mtime_ns == first
    assert "a.mp3" in capsys.readouterr().err  # the skip is reported, not shown as converted
