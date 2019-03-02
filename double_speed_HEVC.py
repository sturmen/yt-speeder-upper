#! python3

import ffmpeg
import sys
import os

MAX_HEIGHT = 1440
MAX_WIDTH = 2960

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
  if (height >= 1440):
    return 23
  elif (height >= 1080):
    return 25
  else:
    return 28

def main():
  in_file_name = sys.argv[1]
  new_name = os.path.splitext(in_file_name)[0] + "2XHEVC.mp4"
  new_height = get_height(in_file_name)

  inputObject = ffmpeg.input(in_file_name)
  v1 = inputObject['v'].setpts("0.5*PTS")
  if (new_height > MAX_HEIGHT):
    v1 = v1.filter('scale', -1, MAX_HEIGHT, force_original_aspect_ratio='decrease')
  a1 = inputObject['a'].filter('atempo', 2.0)

  ffmpeg.output(v1, a1, new_name, format='mp4', pix_fmt='yuv420p', vcodec='libx265', preset='slow', crf=get_crf(new_height), acodec='aac', r=(2.0*get_frame_rate(in_file_name))).run(overwrite_output=True)

if __name__== "__main__":
  main()