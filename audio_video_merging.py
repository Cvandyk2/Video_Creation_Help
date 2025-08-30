import os
import ffmpeg


# Folders
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO_DIR = os.path.join(ROOT, "coding_audio")
VIDEO_DIR = os.path.join(ROOT, "coding_video")
OUTPUT_DIR = os.path.join(ROOT, "ready_coding")

# Encoding settings
FPS = 30
CRF = 20
ABR = "192k"
VIDEO_SPEED = 0.8  # 1.0 = normal, 0.8 = 20% slower, 2.0 = 2x speed


# Deletion settings
DELETE_AUDIO_AFTER = False   # delete audio files from coding_audio after successful mux
DELETE_VIDEO_AFTER = False   # delete matched video files from coding_video after successful mux (base-name matches only)
DELETE_PHOTOS_AFTER = False  # delete photo files from coding_photos after successful mux


def ensure_dirs():
	os.makedirs(OUTPUT_DIR, exist_ok=True)


def list_media(dir_path, exts):
	return [f for f in os.listdir(dir_path) if f.lower().endswith(exts)]


def probe_duration(path):
	p = ffmpeg.probe(path)
	dur = p.get("format", {}).get("duration")
	if dur:
		return float(dur)
	# Fallback: try first stream duration
	for s in p.get("streams", []):
		if s.get("duration"):
			return float(s["duration"])
	return None


def find_matching_video(audio_name, videos):
	base = os.path.splitext(os.path.basename(audio_name))[0].lower()
	for v in videos:
		if os.path.splitext(os.path.basename(v))[0].lower() == base:
			return v, True
	# fallback: first video
	return (videos[0], False) if videos else (None, False)


def build_output_name(audio_path):
	base = os.path.splitext(os.path.basename(audio_path))[0]
	return os.path.join(OUTPUT_DIR, f"{base}.mp4")


def mux_looped(video_path, audio_path, output_path, audio_seconds):
	# Loop video indefinitely, apply speed change via setpts, then cut to audio length
	v_in = ffmpeg.input(video_path, stream_loop=-1)
	a_in = ffmpeg.input(audio_path)
	v_stream = v_in.video
	spd = VIDEO_SPEED if VIDEO_SPEED and VIDEO_SPEED > 0 else 1.0
	if abs(spd - 1.0) > 1e-6:
		v_stream = v_stream.filter('setpts', f'PTS/{spd}')

	# Check for coding_photos images
	photos_dir = os.path.join(ROOT, "coding_photos")
	photo_exts = (".jpg", ".jpeg", ".png", ".bmp", ".gif")
	photo_files = [f for f in os.listdir(photos_dir) if f.lower().endswith(photo_exts)] if os.path.exists(photos_dir) else []
	photo_paths = [os.path.join(photos_dir, f) for f in photo_files]
	used_photos = list(photo_paths)

	if photo_paths:
		# Probe main video for size
		try:
			probe = ffmpeg.probe(video_path)
			vstreams = [s for s in probe["streams"] if s["codec_type"] == "video"]
			width = int(vstreams[0]["width"])
			height = int(vstreams[0]["height"])
		except Exception:
			width, height = 1280, 720

		# Create temp folder for photo segments
		import tempfile
		tmpdir = tempfile.mkdtemp(prefix="coding_photo_segs_")
		seg_paths = []
		for idx, p in enumerate(photo_paths):
			seg_out = os.path.join(tmpdir, f"photo_{idx:03d}.mp4")
			v = ffmpeg.input(p, loop=1, framerate=FPS, t=3)
			v = v.filter("scale", width, height, force_original_aspect_ratio="decrease") \
				 .filter("pad", width, height, "(ow-iw)/2", "(oh-ih)/2") \
				 .filter("setsar", 1) \
				 .filter("fps", FPS) \
				 .filter("format", "yuv420p")
			out = ffmpeg.output(
				v, seg_out,
				vcodec="libx264",
				r=FPS, pix_fmt="yuv420p", crf=CRF, preset="medium", movflags="+faststart"
			)
			out.overwrite_output().run()
			seg_paths.append(seg_out)

		# Build concat list: main video (trimmed), then photo segments (video only)
		import shutil
		main_seg = os.path.join(tmpdir, "main.mp4")
		ffmpeg.output(
			v_stream, main_seg,
			vcodec="libx264",
			r=FPS, pix_fmt="yuv420p", crf=CRF, preset="medium",
			t=audio_seconds - len(seg_paths)*3, movflags="+faststart"
		).overwrite_output().run()

		concat_list = os.path.join(tmpdir, "concat.txt")
		with open(concat_list, "w", encoding="utf-8") as f:
			f.write(f"file '{main_seg}'\n")
			for seg in seg_paths:
				f.write(f"file '{seg}'\n")

		# Final concat (video only), then overlay audio and trim to audio duration
		concat_vid = os.path.join(tmpdir, "concat_final.mp4")
		ffmpeg.output(
			ffmpeg.input(concat_list, f="concat", safe=0),
			concat_vid,
			vcodec="libx264", r=FPS, pix_fmt="yuv420p", crf=CRF, preset="medium", movflags="+faststart"
		).overwrite_output().run()

		ffmpeg.output(
			ffmpeg.input(concat_vid),
			a_in,
			output_path,
			vcodec="libx264", acodec="aac", audio_bitrate=ABR,
			r=FPS, pix_fmt="yuv420p", crf=CRF, preset="medium",
			t=audio_seconds, movflags="+faststart"
		).overwrite_output().run()

		# Cleanup temp files
		shutil.rmtree(tmpdir, ignore_errors=True)
		# Optionally delete used photos
		if DELETE_PHOTOS_AFTER:
			for p in used_photos:
				try:
					os.remove(p)
					print(f"Deleted photo: {os.path.basename(p)}")
				except Exception as de:
					print(f"Could not delete photo {p}: {de}")
	else:
		# No photos: normal mux
		(
			ffmpeg
			.output(
				v_stream,
				a_in,
				output_path,
				vcodec="libx264",
				acodec="aac",
				audio_bitrate=ABR,
				r=FPS,
				pix_fmt="yuv420p",
				crf=CRF,
				preset="medium",
				t=audio_seconds,
				movflags="+faststart",
			)
			.overwrite_output()
			.run()
		)


def main():
	ensure_dirs()
	audio_files = list_media(AUDIO_DIR, (".mp3", ".wav", ".m4a", ".aac", ".flac"))
	video_files = list_media(VIDEO_DIR, (".mp4", ".mov", ".mkv", ".avi"))

	if not audio_files:
		raise ValueError("No audio files found in coding_audio")
	if not video_files:
		raise ValueError("No video files found in coding_video")

	# Use absolute paths
	audio_paths = [os.path.join(AUDIO_DIR, f) for f in audio_files]
	video_paths = [os.path.join(VIDEO_DIR, f) for f in video_files]

	successes = []  # (audio_path, video_path, base_matched)
	for a in audio_paths:
		target_video, matched = find_matching_video(a, video_paths)
		if not target_video:
			print(f"Skip {a}: no video available")
			continue
		dur = probe_duration(a)
		if not dur or dur <= 0:
			print(f"Skip {a}: could not determine audio duration")
			continue
		out = build_output_name(a)
		print(f"Mux: audio='{os.path.basename(a)}' ({dur:.2f}s) + video='{os.path.basename(target_video)}'{' [matched]' if matched else ''} -> {os.path.basename(out)}")
		try:
			mux_looped(target_video, a, out, dur)
			successes.append((a, target_video, matched))
		except ffmpeg.Error as e:
			print(f"FFmpeg failed for {a}: {e}")

	# Optional deletion after processing all files
	if successes and (DELETE_AUDIO_AFTER or DELETE_VIDEO_AFTER):
		if DELETE_AUDIO_AFTER:
			for a, _, _ in successes:
				try:
					os.remove(a)
					print(f"Deleted audio: {os.path.basename(a)}")
				except Exception as de:
					print(f"Could not delete audio {a}: {de}")
		if DELETE_VIDEO_AFTER:
			# Delete only videos that were base-name matches (safer, avoids deleting shared fallback video)
			vids = {v for _, v, matched in successes if matched}
			for v in vids:
				try:
					os.remove(v)
					print(f"Deleted video: {os.path.basename(v)}")
				except Exception as de:
					print(f"Could not delete video {v}: {de}")


if __name__ == "__main__":
	main()

