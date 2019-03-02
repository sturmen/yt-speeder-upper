#! python3

import ffmpeg
import sys
import os
import youtube_dl

MAX_HEIGHT = 1440
MAX_WIDTH = 2960
FILE_NAME_TEMPLATE = "%(uploader)s - %(title)s - %(id)s"

def get_height(filename):
  probe = ffmpeg.probe(filename)
  video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
  height = int(video_stream['height'])
  return height

def get_frame_rate(filename):
  probe = ffmpeg.probe(filename)
  video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
  fps = eval(video_stream['r_frame_rate'])
  print(fps)
  return float(fps)

def get_crf(height):
  if (height > 1080):
    return 23
  elif (height > 720):
    return 25
  else:
    return 28

def add_file_name(extracted_info):
  constructed_file_name = FILE_NAME_TEMPLATE % {"uploader": extracted_info["uploader"], "title": extracted_info["title"], "id": extracted_info["id"]}
  constructed_file_name += ".mkv"
  print(constructed_file_name)
  return constructed_file_name

def main():
  downloaded_videos = []
  ydl_opts = {
    'format': 'bestvideo+bestaudio/best',
    'outtmpl': FILE_NAME_TEMPLATE,
    'merge_output_format': 'mkv'
  }

  with youtube_dl.YoutubeDL(ydl_opts) as ydl:
    for url in sys.argv[1:]:
      extracted_info = ydl.extract_info(url)
      downloaded_videos.append(add_file_name(extracted_info))

  for in_file_name in downloaded_videos:
    new_name = os.path.splitext(in_file_name)[0] + " [2XHEVC].mp4"
    new_height = get_height(in_file_name)

    inputObject = ffmpeg.input(in_file_name)
    v1 = inputObject['v'].setpts("0.5*PTS")
    if (new_height > MAX_HEIGHT):
      v1 = v1.filter('scale', -1, MAX_HEIGHT, force_original_aspect_ratio='decrease')
    a1 = inputObject['a'].filter('atempo', 2.0)

    ffmpeg.output(v1, a1, new_name, format='mp4', pix_fmt='yuv420p', vcodec='libx265', preset='slow', crf=get_crf(new_height), acodec='aac', r=(2.0*get_frame_rate(in_file_name))).run(overwrite_output=True)

if __name__== "__main__":
  main()