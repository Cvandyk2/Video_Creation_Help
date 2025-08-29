import os
import ffmpeg


# Settings
TOTAL_MINUTES = 30  # Total duration of output video in minutes
COVER_IMAGE = "asmr_cover.png"
COVER_DURATION = 2  # seconds
RAW_FOLDER = "raw_asmr"
OUTPUT_FOLDER = "ready_asmr"
DELETE_OLD_VIDEOS = False  # Set to True to delete processed videos from raw_asmr

# Encoding knobs
FPS = 30                 # target output fps
CRF = 20                 # visual quality for x264 (lower is higher quality)
ABR = "192k"             # audio bitrate
ENCODER = "libx264"      # keep software x264 for best quality; optional: "h264_videotoolbox"
PRESET = "faster"        # faster uses less CPU at same CRF (larger files, same quality)
THREADS = 3              # 0=auto; set to a small number to reduce CPU spikes
USE_HWACCEL_DECODE = True  # use macOS VideoToolbox for hardware-accelerated decode

# Output size budget
MAX_OUTPUT_SIZE_GB = 1.0   # hard cap for final file size
SIZE_SAFETY = 0.98         # safety factor to stay under the cap


def _parse_fps(rate_str):
    try:
        if not rate_str or rate_str == "0/0":
            return None
        if "/" in rate_str:
            n, d = rate_str.split("/")
            return float(n) / float(d) if float(d) != 0 else None
        return float(rate_str)
    except Exception:
        return None


def probe_video(path):
    p = ffmpeg.probe(path)
    vstreams = [s for s in p["streams"] if s["codec_type"] == "video"]
    astreams = [s for s in p["streams"] if s["codec_type"] == "audio"]
    if not vstreams:
        raise RuntimeError("no video stream")
    width = int(vstreams[0]["width"]) 
    height = int(vstreams[0]["height"]) 
    src_fps = _parse_fps(vstreams[0].get("avg_frame_rate") or vstreams[0].get("r_frame_rate"))
    dur = p.get("format", {}).get("duration")
    if dur:
        duration = float(dur)
    else:
        duration = float(vstreams[0].get("duration", 0) or 0)
        if not duration:
            duration = 5.0
    has_audio = len(astreams) > 0
    a_rate = int(astreams[0].get("sample_rate")) if has_audio and astreams[0].get("sample_rate") else None
    a_ch = astreams[0].get("channels") if has_audio else None
    a_codec = astreams[0].get("codec_name") if has_audio else None
    return width, height, duration, has_audio, src_fps, a_rate, a_ch, a_codec


def _maybe_global(stream):
    if USE_HWACCEL_DECODE:
        stream = stream.global_args('-hwaccel', 'videotoolbox')
    return stream


def _parse_abr_to_bps(abr: str) -> int:
    # e.g., "192k" -> 192000, "128000" -> 128000
    s = abr.strip().lower()
    if s.endswith('k'):
        return int(float(s[:-1]) * 1000)
    if s.endswith('m'):
        return int(float(s[:-1]) * 1000_000)
    return int(float(s))


def compute_bitrate_budget(total_seconds: float, audio_bps: int) -> tuple[str, str, str]:
    # Compute target video bitrate to keep final size under MAX_OUTPUT_SIZE_GB
    max_bytes = int(MAX_OUTPUT_SIZE_GB * SIZE_SAFETY * (1024 ** 3))
    if total_seconds <= 0:
        total_seconds = 1
    total_bits_budget = max_bytes * 8
    video_bps = int(total_bits_budget / total_seconds) - audio_bps
    # Clamp to sane bounds
    min_bps = 600_000
    if video_bps < min_bps:
        video_bps = min_bps
    # Build ffmpeg arg strings
    vb = f"{video_bps // 1000}k"
    maxrate = vb
    bufsize = f"{(video_bps * 2) // 1000}k"
    return vb, maxrate, bufsize


def make_cover_segment(cover_image, width, height, out_path, vb: str, maxrate: str, bufsize: str):
    v = ffmpeg.input(cover_image, loop=1, framerate=FPS, t=COVER_DURATION)
    v = v.filter("scale", width, height, force_original_aspect_ratio="decrease") \
         .filter("pad", width, height, "(ow-iw)/2", "(oh-ih)/2") \
         .filter("setsar", 1) \
         .filter("fps", FPS) \
         .filter("format", "yuv420p")
    a = ffmpeg.input("anullsrc=r=44100:cl=stereo", f="lavfi", t=COVER_DURATION)
    out = ffmpeg.output(
        v, a, out_path,
        vcodec=ENCODER, acodec="aac", audio_bitrate=ABR,
        pix_fmt="yuv420p", r=FPS, shortest=None, movflags="+faststart",
        preset=PRESET, threads=THREADS if THREADS > 0 else None,
        **{"b:v": vb, "maxrate": maxrate, "bufsize": bufsize}
    )
    _maybe_global(out).overwrite_output().run()


def make_forward_segment(src_path, width, height, out_path, has_audio, src_fps, a_rate, a_ch, a_codec, vb: str, maxrate: str, bufsize: str):
    inp = ffmpeg.input(src_path)
    v = inp.video.filter("setsar", 1).filter("format", "yuv420p")
    if not src_fps or abs(src_fps - FPS) > 0.01:
        v = v.filter("fps", FPS)
    if has_audio:
        # Encode audio to known ABR to keep size predictable
        a = inp.audio.filter("aresample", 44100).filter("aformat", sample_fmts="fltp", channel_layouts="stereo")
        acodec = 'aac'
    else:
        # create silence matching duration
        _, _, duration, *_ = probe_video(src_path)
        a = ffmpeg.input("anullsrc=r=44100:cl=stereo", f="lavfi", t=duration).audio
        acodec = 'aac'
    out = ffmpeg.output(
        v, a, out_path,
        vcodec=ENCODER, acodec=acodec, audio_bitrate=ABR,
        pix_fmt="yuv420p", r=FPS,
        preset=PRESET, threads=THREADS if THREADS > 0 else None, movflags="+faststart",
        **{"b:v": vb, "maxrate": maxrate, "bufsize": bufsize}
    )
    _maybe_global(out).overwrite_output().run()


def make_reverse_segment(src_path, width, height, out_path, has_audio, src_fps, vb: str, maxrate: str, bufsize: str):
    inp = ffmpeg.input(src_path)
    v = inp.video.filter("setsar", 1).filter("format", "yuv420p")
    if not src_fps or abs(src_fps - FPS) > 0.01:
        v = v.filter("fps", FPS)
    v = v.filter("reverse")
    if has_audio:
        a = inp.audio.filter("atrim", start=0).filter("areverse").filter("aresample", 44100).filter("aformat", sample_fmts="fltp", channel_layouts="stereo")
    else:
        _, _, duration, *_ = probe_video(src_path)
        a = ffmpeg.input("anullsrc=r=44100:cl=stereo", f="lavfi", t=duration).audio
    out = ffmpeg.output(
        v, a, out_path,
        vcodec=ENCODER, acodec='aac', audio_bitrate=ABR,
        pix_fmt="yuv420p", r=FPS,
        preset=PRESET, threads=THREADS if THREADS > 0 else None, movflags="+faststart",
        **{"b:v": vb, "maxrate": maxrate, "bufsize": bufsize}
    )
    _maybe_global(out).overwrite_output().run()


def concat_segments(list_file, out_path, total_seconds=None):
    inp = ffmpeg.input(list_file, f="concat", safe=0)
    # Re-mux only (no re-encode) for minimal CPU; segments were already normalized
    out_kwargs = dict(vcodec="copy", acodec="copy", movflags="+faststart")
    if total_seconds:
        out_kwargs["t"] = int(total_seconds)
    (
        ffmpeg.output(inp, out_path, **out_kwargs).overwrite_output().run()
    )


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def main():
    ensure_dir(OUTPUT_FOLDER)
    raw_videos = [f for f in os.listdir(RAW_FOLDER) if f.lower().endswith((".mp4", ".mov", ".avi", ".mkv"))]
    if not raw_videos:
        raise ValueError("No videos found in raw_asmr folder!")

    for video in raw_videos:
        src = os.path.abspath(os.path.join(RAW_FOLDER, video))
        base = os.path.splitext(os.path.basename(video))[0]
        out_final = os.path.abspath(os.path.join(OUTPUT_FOLDER, f"asmr_{video}"))
        tmp_dir = os.path.abspath(os.path.join(OUTPUT_FOLDER, f"tmp_{base}"))
        ensure_dir(tmp_dir)

        try:
            width, height, duration, has_audio, src_fps, a_rate, a_ch, a_codec = probe_video(src)
        except Exception as e:
            print(f"Skipping {video}: probe failed ({e})")
            continue

        cover_seg = os.path.join(tmp_dir, "000_cover.mp4")
        fwd_seg = os.path.join(tmp_dir, "001_forward.mp4")
        rev_seg = os.path.join(tmp_dir, "002_reverse.mp4")

        # Compute bitrate budget to keep final under cap
        total_seconds = TOTAL_MINUTES * 60
        audio_bps = _parse_abr_to_bps(ABR)
        vb, maxrate, bufsize = compute_bitrate_budget(total_seconds, audio_bps)

        # Build segments at target bitrate
        make_cover_segment(COVER_IMAGE, width, height, cover_seg, vb, maxrate, bufsize)
        make_forward_segment(src, width, height, fwd_seg, has_audio, src_fps, a_rate, a_ch, a_codec, vb, maxrate, bufsize)
        make_reverse_segment(src, width, height, rev_seg, has_audio, src_fps, vb, maxrate, bufsize)

        # Build concat list
        playlist = [cover_seg]
        current = COVER_DURATION
        while current < total_seconds + duration:  # slightly overbuild for safety
            playlist.append(fwd_seg)
            current += duration
            playlist.append(rev_seg)
            current += duration

        list_path = os.path.join(tmp_dir, "concat.txt")
        with open(list_path, "w", encoding="utf-8") as f:
            for p in playlist:
                f.write(f"file '{os.path.abspath(p)}'\n")

        # Concat and trim to target duration in one pass
        concat_segments(list_path, out_final, total_seconds=total_seconds)
        print(f"Exported {out_final}")

        # Cleanup temp dir
        try:
            for fn in os.listdir(tmp_dir):
                os.remove(os.path.join(tmp_dir, fn))
            os.rmdir(tmp_dir)
        except Exception:
            pass

        if DELETE_OLD_VIDEOS:
            try:
                os.remove(src)
                print(f"Deleted {src}")
            except Exception as e:
                print(f"Error deleting {src}: {e}")


if __name__ == "__main__":
    main()
