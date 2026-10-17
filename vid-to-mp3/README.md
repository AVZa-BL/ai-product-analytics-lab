# vid-to-mp3

Takes the sound from the video files in a folder (iPhone `.MOV` / `.mp4`) and saves it as MP3, using [ffmpeg](https://ffmpeg.org). The video is not changed.

## Setup

ffmpeg must be on your `PATH` (the script checks and tells you if not):

```bash
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Debian / Ubuntu
```

No Python packages are needed (Python 3.10 or newer).

## Use

Put the videos in the target folder, then run the script. The target defaults to `~/Projects/mini-projs/vid-to-mp3/input`; the MP3s are written to its `mp3` subfolder:

```text
input/
├── IMG_1234.MOV        <- your videos (.mov, .mp4, .m4v)
├── IMG_1235.MOV
└── mp3/                <- created by the script
    ├── IMG_1234.mp3
    └── IMG_1235.mp3
```

```bash
python vid_to_mp3.py                       # the default target
python vid_to_mp3.py ~/Movies/trip         # another target; writes ~/Movies/trip/mp3/
```

Only the files directly in the target are converted (subfolders, including `mp3`, are not searched). Existing MP3s are never overwritten; the file is reported and the rest carries on. The exit code is 1 if any file failed (for example a video with no audio track) or the target holds no videos, and 2 if ffmpeg is missing or the target is not a folder.

The quality is variable bit rate, about 190 kbit/s (`-q:a 2`), a common "transparent for most listeners" setting. For a different one, change that value in `vid_to_mp3.py` (0 is best, 9 smallest).

The same thing in one raw command, if you do not want the script:

```bash
ffmpeg -i IMG_1234.MOV -vn -c:a libmp3lame -q:a 2 IMG_1234.mp3
```

## Test

```bash
python -m pip install pytest
python -m pytest -q
```

The tests build their own one-second videos with ffmpeg and are skipped if it is missing. They are not part of the repository's CI workflow.
