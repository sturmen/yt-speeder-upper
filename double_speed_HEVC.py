#! python3

import ffmpeg
import sys
import os
import youtube_dl

MAX_HEIGHT = 1440
MAX_WIDTH = 2960
MAX_INPUT_FRAME_RATE = 60
MAX_OUTPUT_FRAME_RATE = 60
FILE_NAME_TEMPLATE = "%(uploader)s_%(title)s_%(id)s"

def get_height(filename):
  try:
    probe = ffmpeg.probe(filename)
    video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
    height = int(video_stream['height'])
    return height
  except ffmpeg.Error as e:
    print(e.stderr)
    raise e

def get_frame_rate(filename):
  probe = ffmpeg.probe(filename)
  video_stream = next((stream for stream in probe['streams'] if stream['codec_type'] == 'video'), None)
  fps = eval(video_stream['r_frame_rate'])
  return float(fps)
  
def main():
  downloaded_videos = []
  ydl_opts = {
    'format': 'bestvideo[fps<=%(fps)s]+bestaudio/best' % {"fps": MAX_INPUT_FRAME_RATE},
    'outtmpl': FILE_NAME_TEMPLATE,
    'restrictfilenames': True,
    'merge_output_format': 'mkv'
  }

  with youtube_dl.YoutubeDL(ydl_opts) as ydl:
    for url in sys.argv[1:]:
      try:
        extracted_info = ydl.extract_info(url)
        if "_type" in extracted_info and "entries" in extracted_info and extracted_info["_type"] is 'playlist':
          for entry in extracted_info["entries"]:
            filename = ydl.prepare_filename(entry) + ".mkv"
            if filename not in downloaded_videos:
              downloaded_videos.append(filename)
        else:
          filename = ydl.prepare_filename(extracted_info) + ".mkv"
          if filename not in downloaded_videos:
            downloaded_videos.append(filename)
      except:
        print(f'failed to download {url}')

  for in_file_name in downloaded_videos:
    file_name_root = os.path.splitext(in_file_name)[0]
    destination_file = file_name_root  + "_[2XHEVC].mp4"
    if os.path.isfile(destination_file):
      continue

    new_height = get_height(in_file_name)

    inputObject = ffmpeg.input(in_file_name)
    v1 = inputObject['v'].setpts("0.5*PTS")
    if (new_height > MAX_HEIGHT):
      v1 = v1.filter('scale', -2, MAX_HEIGHT)
    a1 = inputObject['a'].filter('atempo', 2.0)

    temp_file_name = file_name_root + ".tmp"

    ffmpeg.output(v1, a1, temp_file_name, format='mp4', pix_fmt='yuv420p', vcodec='libx265', preset='ultrafast', crf=20, tune="fastdecode", vtag="hvc1", acodec='aac', audio_bitrate="128k", r=min(2.0*get_frame_rate(in_file_name), MAX_OUTPUT_FRAME_RATE)).run(overwrite_output=True)
    os.rename(temp_file_name, destination_file)

if __name__== "__main__":
  main()