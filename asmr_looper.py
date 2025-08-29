import os
import math
import ffmpeg


# Settings
TOTAL_MINUTES = 30  # Total duration of output video in minutes
COVER_IMAGE = "asmr_cover.png"
COVER_DURATION = 2  # seconds
RAW_FOLDER = "raw_asmr"
OUTPUT_FOLDER = "ready_asmr"
DELETE_OLD_VIDEOS = False  # Set to True to delete processed videos from raw_asmr

# Encoding knobs
FPS = 30
CRF = 20
ABR = "192k"


def probe_video(path):
    p = ffmpeg.probe(path)
    vstreams = [s for s in p["streams"] if s["codec_type"] == "video"]
    astreams = [s for s in p["streams"] if s["codec_type"] == "audio"]
    if not vstreams:
        raise RuntimeError("no video stream")
    width = int(vstreams[0]["width"]) 
    height = int(vstreams[0]["height"]) 
    dur = p.get("format", {}).get("duration")
    if dur:
        duration = float(dur)
    else:
        duration = float(vstreams[0].get("duration", 0) or 0)
        if not duration:
            duration = 5.0
    return width, height, duration, (len(astreams) > 0)


def make_cover_segment(cover_image, width, height, out_path):
    v = ffmpeg.input(cover_image, loop=1, framerate=FPS, t=COVER_DURATION)
    v = v.filter("scale", width, height, force_original_aspect_ratio="decrease") \
         .filter("pad", width, height, "(ow-iw)/2", "(oh-ih)/2") \
         .filter("setsar", 1) \
         .filter("fps", FPS) \
         .filter("format", "yuv420p")
    a = ffmpeg.input("anullsrc=r=44100:cl=stereo", f="lavfi", t=COVER_DURATION)
    (
        ffmpeg
        .output(v, a, out_path, vcodec="libx264", acodec="aac", audio_bitrate=ABR, 
                pix_fmt="yuv420p", r=FPS, shortest=None, movflags="+faststart")
        .overwrite_output()
        .run()
    )


def make_forward_segment(src_path, width, height, out_path, has_audio):
    inp = ffmpeg.input(src_path)
    v = inp.video.filter("fps", FPS).filter("setsar", 1).filter("format", "yuv420p")
    if has_audio:
        a = inp.audio.filter("aresample", 44100).filter("aformat", sample_fmts="fltp", channel_layouts="stereo")
    else:
        # create silence matching duration
        _, _, duration, _ = probe_video(src_path)
        a = ffmpeg.input("anullsrc=r=44100:cl=stereo", f="lavfi", t=duration).audio
    (
        ffmpeg
        .output(v, a, out_path, vcodec="libx264", acodec="aac", audio_bitrate=ABR, 
                pix_fmt="yuv420p", r=FPS, crf=CRF, preset="medium", movflags="+faststart")
        .overwrite_output()
        .run()
    )


def make_reverse_segment(src_path, width, height, out_path, has_audio):
    inp = ffmpeg.input(src_path)
    v = inp.video.filter("fps", FPS).filter("setsar", 1).filter("format", "yuv420p").filter("reverse")
    if has_audio:
        a = inp.audio.filter("atrim", start=0).filter("areverse").filter("aresample", 44100).filter("aformat", sample_fmts="fltp", channel_layouts="stereo")
    else:
        _, _, duration, _ = probe_video(src_path)
        a = ffmpeg.input("anullsrc=r=44100:cl=stereo", f="lavfi", t=duration).audio
    (
        ffmpeg
        .output(v, a, out_path, vcodec="libx264", acodec="aac", audio_bitrate=ABR, 
                pix_fmt="yuv420p", r=FPS, crf=CRF, preset="medium", movflags="+faststart")
        .overwrite_output()
        .run()
    )


def concat_segments(list_file, out_path, total_seconds=None):
    inp = ffmpeg.input(list_file, f="concat", safe=0)
    out_kwargs = dict(vcodec="libx264", acodec="aac", audio_bitrate=ABR, pix_fmt="yuv420p", r=FPS, preset="medium", crf=CRF, movflags="+faststart")
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
            width, height, duration, has_audio = probe_video(src)
        except Exception as e:
            print(f"Skipping {video}: probe failed ({e})")
            continue

        cover_seg = os.path.join(tmp_dir, "000_cover.mp4")
        fwd_seg = os.path.join(tmp_dir, "001_forward.mp4")
        rev_seg = os.path.join(tmp_dir, "002_reverse.mp4")

        # Build segments
        make_cover_segment(COVER_IMAGE, width, height, cover_seg)
        make_forward_segment(src, width, height, fwd_seg, has_audio)
        make_reverse_segment(src, width, height, rev_seg, has_audio)

        # Build concat list
        total_seconds = TOTAL_MINUTES * 60
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
