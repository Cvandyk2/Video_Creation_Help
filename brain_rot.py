
# === SETTINGS ===
DELETE_OLD_VIDEOS = True  # Set to True to delete processed videos from raw_short
THREADS = 2                # Number of FFmpeg threads to use (lower = less CPU strain)
CRF = 23                   # Constant Rate Factor for libx264 (lower = higher quality, higher = faster/smaller)

import os
import random
import ffmpeg

# === CONFIG ===
raw_short_folder = "raw_short"
brainrot_folder = "brainrot_videos"
output_folder = "ready_short"
os.makedirs(output_folder, exist_ok=True)

brainrot_videos = [f for f in os.listdir(brainrot_folder) if f.endswith((".mp4", ".mov", ".avi", ".mkv"))]
if not brainrot_videos:
    raise ValueError("No videos found in brainrot folder!")

raw_short_videos = [f for f in os.listdir(raw_short_folder) if f.endswith((".mp4", ".mov", ".avi", ".mkv", ".MOV"))]
if not raw_short_videos:
    raise ValueError("No videos found in raw_short folder!")

def get_video_info(path):
    probe = ffmpeg.probe(path)
    video_streams = [s for s in probe['streams'] if s['codec_type'] == 'video']
    if not video_streams:
        raise ValueError(f"No video stream found in {path}")
    stream = video_streams[0]
    duration = float(stream['duration'])
    width = int(stream['width'])
    height = int(stream['height'])
    return duration, width, height

for main_video in raw_short_videos:
    main_path = os.path.join(raw_short_folder, main_video)
    random_brainrot = os.path.join(brainrot_folder, random.choice(brainrot_videos))

    main_duration, main_w, main_h = get_video_info(main_path)
    brainrot_duration, _, _ = get_video_info(random_brainrot)

    # Loop or trim brainrot to match main video duration
    temp_brainrot = os.path.join(output_folder, f"temp_brainrot_{main_video}")
    temp_brainrot_trimmed = os.path.join(output_folder, f"temp_brainrot_trimmed_{main_video}")
    if brainrot_duration < main_duration:
        # Loop brainrot
        n_loops = int(main_duration // brainrot_duration) + 1
        inputs = [ffmpeg.input(random_brainrot) for _ in range(n_loops)]
        concat = ffmpeg.concat(*inputs, v=1, a=0).node
        v = concat[0]
        ffmpeg.output(v, temp_brainrot, vcodec='libx264').run(overwrite_output=True)
        # Trim to exact duration (write to new file)
        ffmpeg.input(temp_brainrot).output(temp_brainrot_trimmed, t=main_duration, vcodec='libx264').run(overwrite_output=True)
        os.remove(temp_brainrot)
    else:
        # Trim brainrot (write to new file)
        ffmpeg.input(random_brainrot).output(temp_brainrot_trimmed, t=main_duration, vcodec='libx264').run(overwrite_output=True)


    # Crop both videos to 1080x1920 (YouTube Shorts size)
    crop_w, crop_h = 1080, 1920
    temp_main_cropped = os.path.join(output_folder, f"temp_main_cropped_{main_video}")
    temp_brainrot_cropped = os.path.join(output_folder, f"temp_brainrot_cropped_{main_video}")

    # Center crop main video (pad if needed)
    ffmpeg.input(main_path).output(
        temp_main_cropped,
        vf=f"scale={crop_w}:{crop_h}:force_original_aspect_ratio=decrease,pad={crop_w}:{crop_h}:(ow-iw)/2:(oh-ih)/2",
        vcodec='libx264',
        crf=CRF,
        threads=THREADS
    ).run(overwrite_output=True)

    # Zoom in and center crop brainrot video (no pad, always fill)
    ffmpeg.input(temp_brainrot_trimmed).output(
        temp_brainrot_cropped,
        vf=f"scale={crop_w}:{crop_h}:force_original_aspect_ratio=increase,crop={crop_w}:{crop_h}",
        vcodec='libx264',
        crf=CRF,
        threads=THREADS
    ).run(overwrite_output=True)
    os.remove(temp_brainrot_trimmed)

    # Stack vertically and add main video audio
    output_path = os.path.join(output_folder, f"combined_{main_video}")
    stacked = ffmpeg.filter([
        ffmpeg.input(temp_main_cropped),
        ffmpeg.input(temp_brainrot_cropped)
    ], 'vstack')
    # Map video from stacked filter and audio from main video (input 0)
    ffmpeg.output(
        stacked,
        output_path,
        vcodec='libx264',
        acodec='aac',
        map='0:a?',  # map audio from main video if present
        shortest=None,
        s=f"{crop_w}x{crop_h}",
        crf=CRF,
        threads=THREADS
    ).run(overwrite_output=True)

    # Clean up temp files
    os.remove(temp_main_cropped)
    os.remove(temp_brainrot_cropped)

    # Optionally delete processed video
    if DELETE_OLD_VIDEOS:
        try:
            os.remove(main_path)
            print(f"Deleted {main_path}")
        except Exception as e:
            print(f"Error deleting {main_path}: {e}")
