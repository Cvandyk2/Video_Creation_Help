import os
import random
import ffmpeg

# ========================== USER SETTINGS (edit here) ==========================
# General encoding & performance
DELETE_OLD_VIDEOS = True   # If True, delete processed videos from raw_short after export
THREADS = 5                 # FFmpeg threads (lower uses less CPU)
CRF = 21                    # libx264 quality (lower = higher quality, bigger file)
FPS = 60                    # Output frame rate

# Audio master controls
# AUDIO_MODE: 'mix' (keep original + add new) or 'replace' (replace original with new)
AUDIO_MODE = os.environ.get('AUDIO_MODE', 'mix').strip().lower()  # 'mix' or 'replace'
try:
    AUDIO_VOLUME = float(os.environ.get('AUDIO_VOLUME', '1.0'))   # master volume for tracks when not overridden
except Exception:
    AUDIO_VOLUME = 1.0
AUDIO_VOLUME = max(0.0, min(10.0, AUDIO_VOLUME))

# Volume controls (percent of base)
# Set a base volume (as percent), then set per-track percents relative to that base.
# Example: BASE_VOLUME_PERCENT=100, ORIGINAL_VOLUME_PERCENT=80, NEW_VOLUME_PERCENT=120 →
#          original=0.8x, new=1.2x of base, and base multiplies with AUDIO_VOLUME as well.
try:
    BASE_VOLUME_PERCENT = int(os.environ.get('BASE_VOLUME_PERCENT', '75'))  # 100% = 1.0x
except Exception:
    BASE_VOLUME_PERCENT = 100
try:
    ORIGINAL_VOLUME_PERCENT = int(os.environ.get('ORIGINAL_VOLUME_PERCENT', '100'))
except Exception:
    ORIGINAL_VOLUME_PERCENT = 100
try:
    NEW_VOLUME_PERCENT = int(os.environ.get('NEW_VOLUME_PERCENT', '12'))
except Exception:
    NEW_VOLUME_PERCENT = 50
BASE_VOLUME_PERCENT = max(0, min(1000, BASE_VOLUME_PERCENT))
ORIGINAL_VOLUME_PERCENT = max(0, min(1000, ORIGINAL_VOLUME_PERCENT))
NEW_VOLUME_PERCENT = max(0, min(1000, NEW_VOLUME_PERCENT))

# Input/Output folders
raw_short_folder = "raw_short"          # Main/top video input folder
brainrot_folder = "brainrot_videos"     # Background/bottom video folder
output_folder = "ready_short"           # Output folder
audio_folder = os.environ.get('AUDIO_FOLDER', 'short_audio')  # Where to pull background audio files from

# Top panel framing (1080x960 area)
# MAIN_FILL_MODE: 'pad' keeps the entire frame; 'fill' zooms & crops to fill the area.
MAIN_FILL_MODE = os.environ.get('MAIN_FILL_MODE', 'fill').lower()  # 'pad' or 'fill'
try:
    MAIN_ZOOM_PERCENT = int(os.environ.get('MAIN_ZOOM_PERCENT', '100'))  # 100 = no extra zoom
except Exception:
    MAIN_ZOOM_PERCENT = 100

# (Original MAIN_AUDIO_VOLUME is deprecated; per-track volumes are computed below.)

# New/background audio (mixed under the original)
NEW_AUDIO_FILE = os.environ.get('NEW_AUDIO_FILE', os.path.join(audio_folder, 'primary_audio.mp3'))  # If this file doesn't exist, we'll use primary_audio.mp3 or pick randomly from the folder
USE_NEW_AUDIO = os.environ.get('USE_NEW_AUDIO', '1').strip() not in ('0', 'false', 'no')
try:
    NEW_AUDIO_VOLUME = float(os.environ.get('NEW_AUDIO_VOLUME', '0.5'))
except Exception:
    NEW_AUDIO_VOLUME = 1.0
NEW_AUDIO_VOLUME = max(0.0, min(10.0, NEW_AUDIO_VOLUME))

# Random audio selection from audio_folder (disabled by default)
USE_RANDOM_AUDIO = os.environ.get('USE_RANDOM_AUDIO', '1').strip() not in ('0', 'false', 'no')
try:
    AUDIO_EXTENSIONS = tuple(
        ext.strip().lower() for ext in os.environ.get('AUDIO_EXTENSIONS', '.mp3,.wav,.m4a,.aac,.flac,.ogg').split(',') if ext.strip()
    )
except Exception:
    AUDIO_EXTENSIONS = ('.mp3', '.wav', '.m4a', '.aac', '.flac', '.ogg')

# Keep or replace original audio
KEEP_ORIGINAL_AUDIO = os.environ.get('KEEP_ORIGINAL_AUDIO', '1').strip() not in ('0', 'false', 'no')
# Apply master audio mode/volume defaults unless explicitly overridden via env vars
if AUDIO_MODE in ('mix', 'replace'):
    if AUDIO_MODE == 'replace':
        KEEP_ORIGINAL_AUDIO = False
        USE_NEW_AUDIO = True
    elif AUDIO_MODE == 'mix':
        KEEP_ORIGINAL_AUDIO = True
        USE_NEW_AUDIO = True

# Compute final per-track volumes from base percent and master AUDIO_VOLUME,
# unless explicitly provided via env as absolute multipliers.
base_mult = max(0.0, min(10.0, AUDIO_VOLUME * (BASE_VOLUME_PERCENT / 100.0)))
if 'ORIGINAL_AUDIO_VOLUME' not in os.environ:
    ORIGINAL_AUDIO_VOLUME = max(0.0, min(10.0, base_mult * (ORIGINAL_VOLUME_PERCENT / 100.0)))
if 'NEW_AUDIO_VOLUME' not in os.environ:
    NEW_AUDIO_VOLUME = max(0.0, min(10.0, base_mult * (NEW_VOLUME_PERCENT / 100.0)))
# ==============================================================================

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

def has_audio(path):
    try:
        probe = ffmpeg.probe(path)
        astreams = [s for s in probe.get('streams', []) if s.get('codec_type') == 'audio']
        return len(astreams) > 0
    except Exception:
        return False

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
        # Normalize to constant FPS to avoid timing drift
        ffmpeg.output(v, temp_brainrot, vcodec='libx264', r=FPS).run(overwrite_output=True)
        # Trim to exact duration (write to new file)
        ffmpeg.input(temp_brainrot).output(temp_brainrot_trimmed, t=main_duration, vcodec='libx264', r=FPS).run(overwrite_output=True)
        os.remove(temp_brainrot)
    else:
        # Trim brainrot (write to new file)
        ffmpeg.input(random_brainrot).output(temp_brainrot_trimmed, t=main_duration, vcodec='libx264', r=FPS).run(overwrite_output=True)


    # Prepare streams for vertical stack to 1080x1920: make each half 1080x960
    crop_w, crop_h = 1080, 1920
    half_h = crop_h // 2
    temp_main_cropped = os.path.join(output_folder, f"temp_main_cropped_{main_video}")
    temp_brainrot_cropped = os.path.join(output_folder, f"temp_brainrot_cropped_{main_video}")

    # Main video top panel framing
    if MAIN_FILL_MODE == 'fill':
        # Fill: scale up maintaining AR, then crop to 1080x960; apply extra zoom via scale multiplier
        # Compute scale multiplier from percentage; e.g., 110 -> 1.1
        zoom_mult = max(1.0, float(MAIN_ZOOM_PERCENT) / 100.0)
        # We implement extra zoom by scaling to a larger box then cropping back to target area.
        # First, scale to fill the target box; then up-scale by zoom_mult; crop back to exact size.
        vf_chain = (
            f"scale={crop_w}:{half_h}:force_original_aspect_ratio=increase,"
            f"scale=iw*{zoom_mult}:ih*{zoom_mult},"
            f"crop={crop_w}:{half_h}"
        )
    else:
        # Pad: scale down if needed keeping entire frame, then pad to center
        vf_chain = (
            f"scale={crop_w}:{half_h}:force_original_aspect_ratio=decrease,"
            f"pad={crop_w}:{half_h}:(ow-iw)/2:(oh-ih)/2"
        )

    ffmpeg.input(main_path).output(
        temp_main_cropped,
        vf=f"{vf_chain},fps={FPS},setpts=PTS-STARTPTS,format=yuv420p",
        vcodec='libx264',
        crf=CRF,
        r=FPS,
        threads=THREADS
    ).run(overwrite_output=True)

    # Zoom in and center crop brainrot video (no pad, always fill)
    ffmpeg.input(temp_brainrot_trimmed).output(
        temp_brainrot_cropped,
        vf=f"scale={crop_w}:{half_h}:force_original_aspect_ratio=increase,crop={crop_w}:{half_h},fps={FPS},setpts=PTS-STARTPTS,format=yuv420p",
        vcodec='libx264',
        crf=CRF,
        r=FPS,
        threads=THREADS
    ).run(overwrite_output=True)
    os.remove(temp_brainrot_trimmed)

    # Stack vertically and add main video audio
    output_path = os.path.join(output_folder, f"combined_{main_video}")
    main_in = ffmpeg.input(temp_main_cropped)
    brain_in = ffmpeg.input(temp_brainrot_cropped)
    stacked = ffmpeg.filter([main_in.video, brain_in.video], 'vstack')
    # Output stacked video with audio handling:
    # - If KEEP_ORIGINAL_AUDIO and main has audio, include it with ORIGINAL_AUDIO_VOLUME.
    # - If USE_NEW_AUDIO and NEW_AUDIO_FILE exists, include it with NEW_AUDIO_VOLUME; loop/trim to match.
    # - If neither present, output silence.
    main_has_audio = has_audio(main_path)
    audio_streams = []
    if KEEP_ORIGINAL_AUDIO and main_has_audio:
        a = main_in.audio
        if abs(ORIGINAL_AUDIO_VOLUME - 1.0) > 1e-3:
            a = a.filter('volume', volume=ORIGINAL_AUDIO_VOLUME)
        audio_streams.append(a)
    new_audio_in = None
    # Build candidate list from audio_folder
    candidates = []
    try:
        candidates = [
            os.path.join(audio_folder, f)
            for f in os.listdir(audio_folder)
            if f.lower().endswith(AUDIO_EXTENSIONS)
        ]
    except Exception:
        candidates = []
    chosen_new_audio = None
    if USE_NEW_AUDIO:
        # Priority 1: random pick if enabled and candidates available
        if USE_RANDOM_AUDIO and candidates:
            chosen_new_audio = random.choice(candidates)
        # Priority 2: explicit NEW_AUDIO_FILE if it exists
        elif NEW_AUDIO_FILE and os.path.exists(NEW_AUDIO_FILE):
            chosen_new_audio = NEW_AUDIO_FILE
        # Priority 3: audio_folder/primary_audio.mp3 if present (explicit primary file)
        elif os.path.exists(os.path.join(audio_folder, 'primary_audio.mp3')):
            chosen_new_audio = os.path.join(audio_folder, 'primary_audio.mp3')
        # Priority 4: deterministic fallback to first by name
        elif candidates:
            chosen_new_audio = sorted(candidates)[0]
    if chosen_new_audio and os.path.exists(chosen_new_audio):
        # Load new audio; loop or trim to main duration
        new_audio_input = ffmpeg.input(chosen_new_audio)
        # atrim ensures exact duration; aevalsrc of 0 isn't needed here
        a_stream = new_audio_input.audio.filter('aloop', size=int(FPS*2), loops=100000) if False else new_audio_input.audio
        # Apply volume
        if abs(NEW_AUDIO_VOLUME - 1.0) > 1e-3:
            a_stream = a_stream.filter('volume', volume=NEW_AUDIO_VOLUME)
        # Force duration
        a_stream = a_stream.filter('atrim', duration=main_duration).filter('asetpts', 'N/SR/TB')
        audio_streams.append(a_stream)
        try:
            print(f"Using background audio: {os.path.basename(chosen_new_audio)}")
        except Exception:
            pass

    if len(audio_streams) == 0:
        silence = ffmpeg.input("anullsrc=r=44100:cl=stereo", f="lavfi", t=main_duration)
        out_audio = silence
    elif len(audio_streams) == 1:
        out_audio = audio_streams[0]
    else:
        # Mix original and new audio; normalize volume to avoid clipping by averaging
        out_audio = ffmpeg.filter(audio_streams, 'amix', inputs=len(audio_streams), duration='first', dropout_transition=0)
        # optional: dynaudnorm or loudnorm could go here; keeping simple

    ffmpeg.output(
        stacked,
        out_audio,
        output_path,
        vcodec='libx264',
        acodec='aac',
        r=FPS,
        pix_fmt='yuv420p',
        crf=CRF,
        threads=THREADS,
        t=main_duration
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
