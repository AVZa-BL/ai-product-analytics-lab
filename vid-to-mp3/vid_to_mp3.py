"""Extract the audio of every video in a folder (e.g. iPhone .MOV) into MP3 files with ffmpeg.

The MP3s go into the subfolder "mp3" of that folder.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_TARGET = Path.home() / "Projects/mini-projs/vid-to-mp3/input"
OUT_SUBFOLDER = "mp3"
VIDEO_SUFFIXES = {".mov", ".mp4", ".m4v"}


def convert(video: Path, out_dir: Path) -> Path:
    """Write <video name>.mp3 into out_dir and return its path.

    Raises FileExistsError rather than overwrite, and RuntimeError if ffmpeg fails
    (for instance when the video has no audio track).
    """
    mp3 = out_dir / f"{video.stem}.mp3"
    if mp3.exists():
        raise FileExistsError(mp3)
    mp3.parent.mkdir(parents=True, exist_ok=True)
    # -vn drops the video; -n makes ffmpeg itself refuse to overwrite; -q:a 2 is VBR, ~190 kbit/s.
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n", "-i", str(video),
           "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(mp3)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        mp3.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or f"ffmpeg exited with {result.returncode}")
    return mp3


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", nargs="?", type=Path, default=DEFAULT_TARGET,
                        help=f"folder holding the videos (default: {DEFAULT_TARGET})")
    target = parser.parse_args(argv).target

    if shutil.which("ffmpeg") is None:
        print("ffmpeg not found; install it first (macOS: brew install ffmpeg)", file=sys.stderr)
        return 2
    if not target.is_dir():
        print(f"{target} is not a folder", file=sys.stderr)
        return 2
    videos = sorted(f for f in target.iterdir() if f.suffix.lower() in VIDEO_SUFFIXES)
    if not videos:
        print(f"no videos ({', '.join(sorted(VIDEO_SUFFIXES))}) in {target}", file=sys.stderr)
        return 1
    failed = 0
    for video in videos:
        try:
            print(f"{video.name} -> {convert(video, target / OUT_SUBFOLDER)}")
        except (FileExistsError, RuntimeError) as err:
            failed += 1
            print(f"{video.name}: {err}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
