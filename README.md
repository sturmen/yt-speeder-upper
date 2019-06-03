# video-speeder-upper

A Python script to download & re-encode videos to be faster

# Building

`pip3 install ffmpeg-python youtube-dl`

then use Python to run the script as-is, or use PyInstaller to create an executable

# Usage

Requires Python 3, and `ffmpeg` and `ffprobe` in your PATH.

`python3 double_speed_HEVC.py youtube_url_1 youtube_url_2 youtube_url_3 [...]`