# vid-to-mp3

Takes the sound from video files (iPhone `.MOV` / `.mp4`) and saves it as MP3, using [ffmpeg](https://ffmpeg.org). The video is not changed.

## Setup

ffmpeg must be on your `PATH` (the script checks and tells you if not):

```bash
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Debian / Ubuntu
```

No Python packages are needed (Python 3.10 or newer).

## Use

```bash
# one file: writes IMG_1234.mp3 next to IMG_1234.MOV
python vid_to_mp3.py ~/Movies/IMG_1234.MOV

# several files, MP3s collected in one folder (created if missing)
python vid_to_mp3.py -o ~/Music/from-video ~/Movies/*.MOV
```

Existing MP3s are never overwritten; the file is reported and the rest of the batch carries on. The exit code is 1 if any file failed (for example a video with no audio track).

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
