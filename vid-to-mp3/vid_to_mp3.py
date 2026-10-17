"""Extract the audio track of video files (e.g. iPhone .MOV) into MP3 files with ffmpeg."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def convert(video: Path, out_dir: Path | None = None) -> Path:
    """Write <video name>.mp3 next to the video (or in out_dir) and return its path.

    Raises FileExistsError rather than overwrite, and RuntimeError if ffmpeg fails
    (for instance when the video has no audio track).
    """
    mp3 = (out_dir or video.parent) / f"{video.stem}.mp3"
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
    parser.add_argument("videos", nargs="+", type=Path, help="video files to convert")
    parser.add_argument("-o", "--out-dir", type=Path,
                        help="folder for the MP3s (default: next to each video)")
    args = parser.parse_args(argv)

    if shutil.which("ffmpeg") is None:
        print("ffmpeg not found; install it first (macOS: brew install ffmpeg)", file=sys.stderr)
        return 2
    failed = 0
    for video in args.videos:
        try:
            print(f"{video} -> {convert(video, args.out_dir)}")
        except (FileExistsError, RuntimeError) as err:
            failed += 1
            print(f"{video}: {err}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
