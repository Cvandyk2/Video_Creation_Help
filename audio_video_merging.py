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
DELETE_AUDIO_AFTER = True   # delete audio files from coding_audio after successful mux
DELETE_VIDEO_AFTER = True   # delete matched video files from coding_video after successful mux (base-name matches only)


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
	# Sanitize speed
	spd = VIDEO_SPEED if VIDEO_SPEED and VIDEO_SPEED > 0 else 1.0
	if abs(spd - 1.0) > 1e-6:
		v_stream = v_stream.filter('setpts', f'PTS/{spd}')
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

