#! python3
''' Formatted with yapf '''

import ffmpeg
from filelock import Timeout, FileLock
import glob
import json
import sys
import os
import re
import string
from pprint import pprint
import requests
import youtube_dl
from datetime import datetime

MAX_RETRIES = 5
MAX_HEIGHT = 1080
MAX_WIDTH = 1920
MAX_INPUT_FRAME_RATE = 60
MAX_OUTPUT_FRAME_RATE = 60
FILE_NAME_TEMPLATE = "%(id)s"
SPEED_FACTOR = 2.50

BLOCKED_CATEGORIES = ["sponsor", "intro", "outro"]

allowed_chars_pattern = re.compile('[^\w\s-]+')

download_lock_path = "ytdl_download.lock"
download_lock = FileLock(download_lock_path, timeout=1)
encode_lock_path = "ytdl_encode.lock"
encode_lock = FileLock(encode_lock_path, timeout=1)


def get_height(filename):
    try:
        probe = ffmpeg.probe("./" + filename)
        video_stream = next((stream for stream in probe['streams']
                             if stream['codec_type'] == 'video'), None)
        height = int(video_stream['height'])
        return height
    except ffmpeg.Error as e:
        print(e.stderr)
        raise e


def get_frame_rate(filename):
    probe = ffmpeg.probe("./" + filename)
    video_stream = next(
        (stream
         for stream in probe['streams'] if stream['codec_type'] == 'video'),
        None)
    fps = eval(video_stream['r_frame_rate'])
    return float(fps)


def get_total_duration(filename):
    try:
        probe = ffmpeg.probe("./" + filename)
        video_stream = next((stream for stream in probe['streams']
                             if stream['codec_type'] == 'video'), None)
        return get_sec(video_stream['tags']['DURATION'])
    except ffmpeg.Error as e:
        print(e.stderr)
        raise e


def get_sec(time_str):
    """Get Seconds from time."""
    h, m, s = time_str.split(':')
    return int(h) * 3600 + int(m) * 60 + float(s)


def download_videos(videos, opts, retries_remaining):
    result_list = []
    if retries_remaining < 1:
        print('no more retries left. aborting.')
        return result_list

    with youtube_dl.YoutubeDL(opts) as ydl:
        for url in videos:
            try:
                extracted_info = ydl.extract_info(url)
                if "_type" in extracted_info and "entries" in extracted_info and extracted_info[
                        "_type"] == 'playlist':
                    for entry in extracted_info["entries"]:
                        result_list.append(
                            parse_video_info_for_filename(entry))
                else:
                    result_list.append(
                        parse_video_info_for_filename(extracted_info))
            except KeyboardInterrupt:
                print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                print("keyboard interrupt, aborting")
                print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                exit()
            except:
                print(
                    f'failed to download {url}\nretries left: {retries_remaining - 1}'
                )
                return download_videos(videos, opts, retries_remaining - 1)

    return result_list


def parse_video_info_for_filename(entry):
    video_id = entry['id']
    video_title = entry['title']
    uploader = entry['uploader']
    filename = allowed_chars_pattern.sub('', f"{uploader} - {video_title}")
    return video_id, filename


def fetch_sponsored_bits(video_id):
    categories_string = str(BLOCKED_CATEGORIES).replace("'", '"')
    payload = f'videoID={video_id}&categories={categories_string}'
    r = requests.get(f'https://sponsor.ajay.app/api/skipSegments',
                     params=payload)
    output = r.text
    return output


def add_sponsor_video_filter(video_stream, audio_stream, video_id,
                             total_duration):
    sponsored_segment_response = fetch_sponsored_bits(video_id)

    if sponsored_segment_response == 'Not Found':
        print(f"No sponsored segments for {video_id}.")
        return video_stream, audio_stream
    else:
        segments_to_keep = find_worthwhile_clips(
            json.loads(sponsored_segment_response), total_duration)
        time_saved = int(
            round(total_duration - sum([x[1] - x[0]
                                        for x in segments_to_keep])))
        print(
            f"Keeping {segments_to_keep} for {video_id}, saving approximately {time_saved} seconds"
        )
        return trim_video(video_stream, segments_to_keep), trim_audio(
            audio_stream, segments_to_keep)


def trim_video(video_stream, segments_to_keep):
    streams_to_concat = []
    split_streams = video_stream.filter_multi_output('split',
                                                     len(segments_to_keep))
    for i, segment in enumerate(segments_to_keep):
        trimmed_stream = split_streams[i].trim(
            start=segment[0], end=segment[1]).setpts("PTS-STARTPTS")
        streams_to_concat.append(trimmed_stream)
    return ffmpeg.concat(
        *streams_to_concat,
        n=len(streams_to_concat),
    )


def trim_audio(audio_stream, segments_to_keep):
    streams_to_concat = []
    split_streams = audio_stream.filter_multi_output('asplit',
                                                     len(segments_to_keep))
    for i, segment in enumerate(segments_to_keep):
        trimmed_stream = split_streams[i].filter("atrim",
                                                 start=segment[0],
                                                 end=segment[1]).filter(
                                                     "asetpts", "PTS-STARTPTS")
        streams_to_concat.append(trimmed_stream)

    return ffmpeg.concat(
        *streams_to_concat,
        n=len(streams_to_concat),
        v=0,
        a=1,
    )


def find_worthwhile_clips(segments, total_duration):
    output = []
    start = 0.0
    for unwanted_segment in sorted([x['segment'] for x in segments]):
        segment_start = unwanted_segment[0]
        segment_end = unwanted_segment[1]
        if segment_start > start:
            output.append((start, segment_start))
        start = segment_end

    if start < total_duration:
        output.append((start, total_duration))
    return output


def encode_videos(downloaded_videos):
    encoded_video_count = 0

    existing_mkv_files = glob.glob('*.mkv')

    for display_id, file_name_root in downloaded_videos:
        in_file_name = display_id + '.mkv'
        if in_file_name in existing_mkv_files:
            existing_mkv_files.remove(in_file_name)
        out_file_suffix = f'_{display_id}.mp4'
        existing_file = next(glob.iglob('*' + out_file_suffix), None)
        if existing_file:
            print("%s already exists, skipping" % existing_file)
            continue

        destination_file = file_name_root + out_file_suffix

        new_height = get_height(in_file_name)

        inputObject = ffmpeg.input("./" + in_file_name)

        total_length = get_total_duration(in_file_name)

        v1 = inputObject['v']
        a1 = inputObject['a']
        v1, a1 = add_sponsor_video_filter(v1, a1, display_id, total_length)
        v1 = v1.setpts("PTS/%s" % SPEED_FACTOR)
        if (new_height > MAX_HEIGHT):
            v1 = v1.filter('scale',
                           MAX_WIDTH,
                           MAX_HEIGHT,
                           force_original_aspect_ratio="decrease")
            v1 = v1.filter('pad', MAX_WIDTH, MAX_HEIGHT, -1, -1)
        a1 = a1.filter('atempo', SPEED_FACTOR)

        temp_file_name = "./" + display_id + ".tmp"

        output_framerate = min(SPEED_FACTOR * get_frame_rate(in_file_name),
                               MAX_OUTPUT_FRAME_RATE)
        start = datetime.now()
        print("%s encoding %s" %
              (start.strftime("[%d/%m/%Y %H:%M:%S]"), file_name_root))
        try:
            out, err = ffmpeg.output(v1,
                                     a1,
                                     temp_file_name,
                                     format='mp4',
                                     pix_fmt='yuv420p',
                                     vcodec='hevc_nvmpi',
                                     video_bitrate="6M",
                                     preset="slow",
                                     rc="vbr",
                                     vtag="hvc1",
                                     acodec='aac',
                                     audio_bitrate="128k",
                                     r=output_framerate,
                                     **{
                                         'metadata:s:a:0': 'language=eng'
                                     }).global_args('-hide_banner').run(
                                         overwrite_output=True, quiet=True)
            print(out)
            print(err)
            encoded_video_count += 1
            end = datetime.now()
            duration = end - start
            if os.path.isfile(temp_file_name):
                print("%s encoding %s completed in %s" %
                      (end.strftime("[%d/%m/%Y %H:%M:%S]"), file_name_root,
                       duration))
                ffmpeg.output(
                    ffmpeg.input(temp_file_name),
                    destination_file,
                    vcodec="copy",
                    acodec="copy",
                    vtag="hvc1",
                    format='mp4',
                    **{
                        'metadata:s:a:0': 'language=eng',
                    }).global_args('-hide_banner').run(overwrite_output=True)
                os.remove(temp_file_name)
            if os.path.isfile(destination_file):
                print("%s rename successful" % destination_file)
            else:
                print("%s rename failed" % destination_file)
                print(temp_file_name + " still exists: " +
                      os.path.isfile(temp_file_name))
        except ffmpeg._run.Error as err:
            print("Error running ffmpeg!")
            raise

    for outdated_file in existing_mkv_files:
        os.remove(outdated_file)


def main():
    ydl_opts = {
        'format': 'bestvideo[fps<=%(fps)s]+bestaudio/best' % {
            "fps": MAX_INPUT_FRAME_RATE
        },
        'outtmpl': FILE_NAME_TEMPLATE,
        'restrictfilenames': True,
        'merge_output_format': 'mkv'
    }

    downloaded_videos = []
    timestamp = datetime.now().strftime("[%d/%m/%Y %H:%M:%S]")
    try:
        with download_lock:
            print(f"{timestamp} Got download lock.")
            downloaded_videos = download_videos(sys.argv[1:], ydl_opts,
                                                MAX_RETRIES)
    except Timeout:
        print(f"{timestamp} Could not get downloading lock.")

    timestamp = datetime.now().strftime("[%d/%m/%Y %H:%M:%S]")
    try:
        with encode_lock:
            print(f"{timestamp} Got encoding lock.")
            encode_videos(downloaded_videos)
    except Timeout:
        timestamp = datetime.now().strftime("[%d/%m/%Y %H:%M:%S]")
        print(f"{timestamp} Could not get encoding lock.")


if __name__ == "__main__":
    main()
