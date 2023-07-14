#! python
""" Formatted with yapf """

import argparse
import json
import sys
import os
import re
import glob
from datetime import datetime
import yt_dlp
import requests
import ffmpeg

from filelock import Timeout, FileLock
from pathlib import Path

MAX_RETRIES = 5
MAX_HEIGHT = 1328
MAX_WIDTH = 2360
MAX_INPUT_FRAME_RATE = 60
MAX_OUTPUT_FRAME_RATE = 60
FILE_NAME_TEMPLATE = "%(id)s"
SPEED_FACTOR = 2.50

BLOCKED_CATEGORIES = ["sponsor", "selfpromo"]

allowed_chars_pattern = re.compile(r"[^\w\s-]+")

DOWNLOAD_LOCK_PATH = "ytdl_download.lock"
download_lock = FileLock(DOWNLOAD_LOCK_PATH, timeout=1)
ENCODE_LOCK_PATH = "ytdl_encode.lock"
encode_lock = FileLock(ENCODE_LOCK_PATH, timeout=1)

def codec_hevc_nvenc(v1, a1, tmp_file, framerate):
    """ Use an NVIDIA GPU to encode to H.265 """
    return ffmpeg.output(
        v1,
        a1,
        tmp_file,
        format="mp4",
        pix_fmt="p010le",
        vcodec="hevc_nvenc",
        g="600",
        preset="slow",
        cq="20",
        vprofile="main10",
        spatial_aq="1",
        temporal_aq="1",
        rc="vbr",
        vtag="hvc1",
        acodec="libfdk_aac",
        audio_bitrate="128k",
        movflags="+faststart",
        r=framerate,
        **{
            "metadata:s:a:0": "language=eng",
        })

def codec_hevc_qsv(v1, a1, tmp_file, framerate):
    """ Use an Intel CPU/GPU to encode to H.265 """
    return ffmpeg.output(
        v1,
        a1,
        tmp_file,
        format="mp4",
        pix_fmt='p010le',
        vcodec='hevc_qsv',
        preset='slower',
        global_quality="19",
        g="600",
        forced_idr="1",
        vprofile='main10',
        vtag="hvc1",
        acodec="libfdk_aac",
        audio_bitrate="128k",
        movflags="+faststart",
        r=framerate,
        **{
            "metadata:s:a:0": "language=eng",
        })

def codec_av1_nvenc(v1, a1, tmp_file, framerate):
    """ Use an NVIDIA GPU to encode to AV1 """
    return ffmpeg.output(
        v1,
        a1,
        tmp_file,
        format='mp4',
        pix_fmt='yuv420p10le',
        vcodec='av1_nvenc',
        multipass='qres',
        video_bitrate='0',
        preset='slow',
        cq="28",
        vprofile='main10',
        spatial_aq='1',
        temporal_aq='1',
        rc='vbr',
        acodec="libfdk_aac",
        audio_bitrate="128k",
        movflags="+faststart",
        r=framerate,
        **{
            "metadata:s:a:0": "language=eng",
        })

def codec_x264(v1, a1, tmp_file, framerate):
    """ Use CPU encoding to encode to H.264 """
    return ffmpeg.output(
        v1,
        a1,
        tmp_file,
        format="mp4",
        pix_fmt="p010le",
        vcodec="x264",
        g="600",
        preset="slow",
        cq="20",
        vprofile="main10",
        acodec="libfdk_aac",
        audio_bitrate="128k",
        movflags="+faststart",
        r=framerate,
        **{
            "metadata:s:a:0": "language=eng",
        })

def codec_x265(v1, a1, tmp_file, framerate):
    """ Use CPU encoding to encode to H.265 """
    return ffmpeg.output(
        v1,
        a1,
        tmp_file,
        format="mp4",
        pix_fmt="p010le",
        vcodec='libx265',
        preset='medium',
        crf="28",
        g="600",
        vprofile='main10',
        vtag="hvc1",
        acodec="libfdk_aac",
        audio_bitrate="128k",
        movflags="+faststart",
        r=framerate,
        **{
            "metadata:s:a:0": "language=eng",
        })

def codec_av1(v1, a1, tmp_file, framerate):
    """ Use CPU encoding to encode to AV1 """
    return ffmpeg.output(
        v1,
        a1,
        tmp_file,
        format='mp4',
        pix_fmt='yuv420p10le',
        vcodec='libaom-av1',
        multipass='qres',
        video_bitrate='0',
        preset='slow',
        cq="28",
        vprofile='main10',
        spatial_aq='1',
        temporal_aq='1',
        rc='vbr',
        acodec="libfdk_aac",
        audio_bitrate="128k",
        movflags="+faststart",
        r=framerate,
        **{
            "metadata:s:a:0": "language=eng",
        })


CODECS ={"x264": codec_x264, "x265": codec_x265, "av1": codec_av1, "hevc_nvenc":codec_hevc_nvenc, "av1_nvenc": codec_av1_nvenc, "hevc_qsv": codec_hevc_qsv}

def get_height(filename):
    """Calculate the height of the video"""
    try:
        probe = ffmpeg.probe("./" + filename)
        video_stream = next(
            (stream for stream in probe["streams"] if stream["codec_type"] == "video"),
            None,
        )
        height = int(video_stream["height"])
        return height
    except ffmpeg.Error as err:
        print(err.stderr)
        raise err


def get_frame_rate(filename):
    """Calculates the total framerate so we can use a framerate less than MAX_FRAMERATE"""
    probe = ffmpeg.probe("./" + filename)
    video_stream = next(
        (stream for stream in probe["streams"] if stream["codec_type"] == "video"), None
    )
    fps = eval(video_stream["r_frame_rate"])
    return float(fps)


def get_total_duration(filename):
    """Calculates the total duration, for logging purposes."""
    try:
        probe = ffmpeg.probe("./" + filename)
        video_stream = next(
            (stream for stream in probe["streams"] if stream["codec_type"] == "video"),
            None,
        )
        return get_sec(video_stream["tags"]["DURATION"])
    except ffmpeg.Error as err:
        print(err.stderr)
        raise err


def get_sec(time_str):
    """Get Seconds from time."""
    h, m, s = time_str.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def download_videos(videos, opts, retries_remaining):
    """Downloads the videos and also fetches their titles"""
    result_list = []
    if retries_remaining < 1:
        print("no more retries left. aborting.")
        return result_list

    with yt_dlp.YoutubeDL(opts) as ydl:
        for url in videos:
            try:
                extracted_info = ydl.extract_info(url)
                if (
                    "_type" in extracted_info
                    and "entries" in extracted_info
                    and extracted_info["_type"] == "playlist"
                ):
                    for entry in extracted_info["entries"]:
                        result_list.append(parse_video_info_for_filename(entry))
                else:
                    result_list.append(parse_video_info_for_filename(extracted_info))
            except KeyboardInterrupt:
                print("\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                print("keyboard interrupt, aborting")
                print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
                exit()
            except:
                print(
                    f"failed to download {url}\nretries left: {retries_remaining - 1}"
                )
                return download_videos(videos, opts, retries_remaining - 1)

    return result_list


def parse_video_info_for_filename(entry):
    """Get metadata from the response"""
    video_id = entry["id"]
    video_title = fetch_dearrowed_title(video_id)
    if video_title is None:
        video_title = entry["title"]
    uploader = entry["uploader"]
    filename = allowed_chars_pattern.sub("", f"{uploader} - {video_title}")
    return video_id, filename


def fetch_dearrowed_title(video_id):
    """Fetches a new title from DeArrow that is potentially less  clickbait-y"""
    payload = f"videoID={video_id}"
    r = requests.get(
        "https://sponsor.ajay.app/api/branding", params=payload, timeout=10
    )
    data = json.loads(r.text)

    # Initialize max_votes to -1 and most_voted_title to None
    max_votes = -1
    most_voted_title = None

    # Iterate over all titles in the data
    for item in data["titles"]:
        # Check if current title has more votes than max_votes
        if item["votes"] > max_votes:
            # If so, update max_votes and most_voted_title
            max_votes = item["votes"]
            most_voted_title = item["title"]

    if most_voted_title is not None:
        print(f"Setting {most_voted_title} as title for {video_id}")
    else:
        print(f"No DeArrow title found for {video_id}")
    return most_voted_title


def fetch_sponsored_bits(video_id):
    categories_string = str(BLOCKED_CATEGORIES).replace("'", '"')
    payload = f"videoID={video_id}&categories={categories_string}"
    r = requests.get(
        "https://sponsor.ajay.app/api/skipSegments", params=payload, timeout=10
    )
    output = r.text
    return output


def add_sponsor_video_filter(video_stream, audio_stream, video_id, total_duration):
    """Add an FFMPEG filter that slices out the sponsored segments"""
    sponsored_segment_response = fetch_sponsored_bits(video_id)

    if sponsored_segment_response == "Not Found":
        print(f"No sponsored segments for {video_id}.")
        return video_stream, audio_stream
    else:
        try:
            segments_to_keep = find_worthwhile_clips(
                json.loads(sponsored_segment_response), total_duration
            )
            time_saved = int(
                round(total_duration - sum([x[1] - x[0] for x in segments_to_keep]))
            )
            print(
                f"Keeping {segments_to_keep} for {video_id}, saving approximately {time_saved} seconds"
            )
            return trim_video(video_stream, segments_to_keep), trim_audio(
                audio_stream, segments_to_keep
            )
        except json.decoder.JSONDecodeError:
            print(
                f"JSON decoding error for {video_id}, continuing encode without SponsorBlock."
            )
            return video_stream, audio_stream


def trim_video(video_stream, segments_to_keep):
    streams_to_concat = []
    split_streams = video_stream.filter_multi_output("split", len(segments_to_keep))
    for i, segment in enumerate(segments_to_keep):
        trimmed_stream = (
            split_streams[i]
            .trim(start=segment[0], end=segment[1])
            .setpts("PTS-STARTPTS")
        )
        streams_to_concat.append(trimmed_stream)
    return ffmpeg.concat(
        *streams_to_concat,
        n=len(streams_to_concat),
    )


def trim_audio(audio_stream, segments_to_keep):
    streams_to_concat = []
    split_streams = audio_stream.filter_multi_output("asplit", len(segments_to_keep))
    for i, segment in enumerate(segments_to_keep):
        trimmed_stream = (
            split_streams[i]
            .filter("atrim", start=segment[0], end=segment[1])
            .filter("asetpts", "PTS-STARTPTS")
        )
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
    for unwanted_segment in sorted([x["segment"] for x in segments]):
        segment_start = unwanted_segment[0]
        segment_end = unwanted_segment[1]
        if segment_start > start:
            output.append((start, segment_start))
        start = segment_end

    if start < total_duration:
        output.append((start, total_duration))
    return output


def encode_videos(downloaded_videos, codec_label):
    existing_mkv_files = glob.glob("*.mkv")

    for display_id, file_name_root in downloaded_videos:
        in_file_name = display_id + ".mkv"
        if in_file_name in existing_mkv_files:
            existing_mkv_files.remove(in_file_name)
        out_file_suffix = f"_{display_id}.mp4"
        existing_file = next(glob.iglob("*" + out_file_suffix), None)
        if existing_file:
            print("%s already exists, skipping" % existing_file)
            continue

        destination_file = file_name_root + out_file_suffix

        new_height = get_height(in_file_name)

        inputObject = ffmpeg.input("./" + in_file_name)

        total_length = get_total_duration(in_file_name)

        v1 = inputObject["v"]
        a1 = inputObject["a"]
        v1, a1 = add_sponsor_video_filter(v1, a1, display_id, total_length)
        v1 = v1.setpts("PTS/%s" % SPEED_FACTOR)
        if new_height > MAX_HEIGHT:
            v1 = v1.filter(
                "scale", MAX_WIDTH, MAX_HEIGHT, force_original_aspect_ratio="decrease"
            )
        a1 = a1.filter("atempo", SPEED_FACTOR)

        temp_file_name = "./" + display_id + ".tmp"

        output_framerate = min(
            SPEED_FACTOR * get_frame_rate(in_file_name), MAX_OUTPUT_FRAME_RATE
        )
        start = datetime.now()
        print(
            "%s encoding %s" % (start.strftime("[%Y-%m-%d %H:%M:%S]"), file_name_root)
        )
        try:
            codec = CODECS[codec_label]
            out, err = codec(v1, a1, temp_file_name, output_framerate).global_args("-hide_banner").run(overwrite_output=True)
            print(f"Output: {out}")
            print(f"Error: {err}")
            end = datetime.now()
            duration = end - start
            if os.path.isfile(temp_file_name):
                print(
                    "%s encoding %s completed in %s"
                    % (end.strftime("[%Y-%m-%d %H:%M:%S]"), file_name_root, duration)
                )
                os.rename(temp_file_name, destination_file)
            if os.path.isfile(destination_file):
                print("%s rename successful" % destination_file)
            else:
                print("%s rename failed" % destination_file)
                print(
                    temp_file_name + " still exists: " + os.path.isfile(temp_file_name)
                )
        except ffmpeg._run.Error:
            print(f"Error running ffmpeg on {out_file_suffix}!")
            os.remove(temp_file_name)
            Path(f'ERROR_ENCODING_FILE{out_file_suffix}').touch()
            continue

    for outdated_file in existing_mkv_files:
        os.remove(outdated_file)


def main(urls, codec="x265"):
    
    if codec not in CODECS:
        print("Invalid codec specified. Must be one of:")
        for valid_codec in CODECS:
            print(f"\t{valid_codec}")
        exit()

    ydl_opts = {
        "format": "bestvideo+bestaudio/best",
        "outtmpl": FILE_NAME_TEMPLATE,
        "restrictfilenames": True,
        "merge_output_format": "mkv",
    }

    downloaded_videos = []
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    try:
        with download_lock:
            print(f"{timestamp} Got download lock.")
            downloaded_videos = download_videos(urls, ydl_opts, MAX_RETRIES)
    except Timeout:
        print(f"{timestamp} Could not get downloading lock. Exiting early.")
        sys.exit()

    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    try:
        with encode_lock:
            print(f"{timestamp} Got encoding lock.")
            encode_videos(downloaded_videos, codec)
    except Timeout:
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        print(f"{timestamp} Could not get encoding lock.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--codec', help='Video encoder to use')
    parser.add_argument("urls", nargs='*', help="yt-dlp compatible URLs or identifiers")
    args = parser.parse_args()
    main(args.urls, args.codec)