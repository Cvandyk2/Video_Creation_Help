import os
import ffmpeg
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import random
import subprocess
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


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
DELETE_PHOTOS_AFTER = True  # delete photo files from coding_photos after successful mux


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
	print(f"Preparing video stream for {os.path.basename(output_path)}...")
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
		print("Creating photo segments...")
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

		print("Creating main video segment...")
		# Build concat list: main video (trimmed), then photo segments (video only)
		import shutil
		main_seg = os.path.join(tmpdir, "main.mp4")
		ffmpeg.output(
			v_stream, main_seg,
			vcodec="libx264",
			r=FPS, pix_fmt="yuv420p", crf=CRF, preset="medium",
			t=audio_seconds - len(seg_paths)*3, movflags="+faststart"
		).overwrite_output().run()

		print("Concatenating segments...")
		concat_list = os.path.join(tmpdir, "concat.txt")
		with open(concat_list, "w", encoding="utf-8") as f:
			for seg in seg_paths:
				f.write(f"file '{seg}'\n")
			f.write(f"file '{main_seg}'\n")

		# Final concat (video only), then overlay audio and trim to audio duration
		concat_vid = os.path.join(tmpdir, "concat_final.mp4")
		ffmpeg.output(
			ffmpeg.input(concat_list, f="concat", safe=0),
			concat_vid,
			vcodec="libx264", r=FPS, pix_fmt="yuv420p", crf=CRF, preset="medium", movflags="+faststart"
		).overwrite_output().run()

		print("Muxing audio...")
		ffmpeg.output(
			ffmpeg.input(concat_vid),
			a_in,
			output_path,
			vcodec="libx264", acodec="aac", audio_bitrate=ABR,
			r=FPS, pix_fmt="yuv420p", crf=CRF, preset="medium",
			t=audio_seconds, movflags="+faststart"
		).overwrite_output().run()

		# Apply thumbnail overlay
		title = os.path.splitext(os.path.basename(output_path))[0]
		apply_thumbnail_overlay(output_path, title)

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
		print("Muxing video and audio...")
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

		# Apply thumbnail overlay
		title = os.path.splitext(os.path.basename(output_path))[0]
		apply_thumbnail_overlay(output_path, title)

# Thumbnail overlay settings
FONT_SIZE = 300

# 6 different neon colors
NEON_COLORS = [
    (0, 255, 255),   # Cyan
    (255, 0, 255),   # Magenta
    (255, 255, 0),   # Yellow
    (0, 255, 0),     # Green
    (255, 0, 0),     # Red
    (255, 165, 0),   # Orange
]

# Try to load Impact font for more neon-like appearance, fallback to Arial, then default
try:
    FONT_PATH = '/Library/Fonts/Impact.ttf'
    font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
except:
    try:
        FONT_PATH = '/Library/Fonts/Arial.ttf'
        font = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    except:
        FONT_PATH = None
        font = ImageFont.load_default()

def has_audio(filepath):
    try:
        result = subprocess.run(['ffprobe', '-i', filepath, '-show_streams', '-select_streams', 'a', '-loglevel', 'error'], capture_output=True, text=True)
        return result.returncode == 0 and 'codec_type=audio' in result.stdout
    except:
        return False

def add_neon_text(frame, text, font, color):
    # Convert frame to PIL Image
    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img_pil)
    
    # Text wrapping
    max_width = img_pil.width - 100  # margin
    words = text.split()
    lines = []
    current_line = ""
    for word in words:
        test_line = current_line + " " + word if current_line else word
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w_test = bbox[2] - bbox[0]
        if w_test > max_width:
            if current_line:
                lines.append(current_line)
                current_line = word
            else:
                lines.append(word)  # force long word
        else:
            current_line = test_line
    if current_line:
        lines.append(current_line)
    
    # Angle for text
    angle = 10  # slight right tilt upward
    
    # Process each line
    text_images = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        # Create text image with transparency
        text_img = Image.new('RGBA', (w + 80, h + 80), (0, 0, 0, 0))
        draw_text = ImageDraw.Draw(text_img)
        
        # Draw thicker white outline around text
        outline_offsets = []
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                if abs(dx) + abs(dy) <= 5:  # Diamond shape to avoid too many pixels
                    outline_offsets.append((dx, dy))
        for dx, dy in outline_offsets:
            draw_text.text((20 + dx, 20 + dy), line, font=font, fill=(255, 255, 255, 255))
        
        # Glow colors
        glow_offsets = [8, 4, 0]
        glow_colors = [
            tuple(min(255, c + 50) for c in color) + (255,),
            tuple(max(0, c - 50) for c in color) + (255,),
            color + (255,)
        ]
        
        # Draw glows
        for offset, glow_color in zip(glow_offsets, glow_colors):
            draw_text.text((20 - offset, 20 - offset), line, font=font, fill=glow_color)
            draw_text.text((20 + offset, 20 + offset), line, font=font, fill=glow_color)
        
        # Draw thin black outline around the main text
        black_outline_offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]
        for dx, dy in black_outline_offsets:
            draw_text.text((20 + dx, 20 + dy), line, font=font, fill=(0, 0, 0, 255))
        
        draw_text.text((20, 20), line, font=font, fill=color + (255,))
        
        # Rotate
        rotated = text_img.rotate(angle, expand=True)
        text_images.append(rotated)
    
    # Position lines
    total_height = sum(img.height for img in text_images) + (len(text_images) - 1) * 5
    y_start = max(50, (img_pil.height - total_height) // 5)  # Ensure minimum margin from top
    x_center = img_pil.width // 2
    
    # Draw semi-transparent black background covering the whole screen
    bg_overlay = Image.new('RGBA', (img_pil.width, img_pil.height), (0, 0, 0, 120))  # Semi-transparent black
    img_pil.paste(bg_overlay, (0, 0), bg_overlay)
    
    current_y = y_start
    for rotated in text_images:
        x = x_center - rotated.width // 2
        img_pil.paste(rotated, (x, current_y), rotated)
        current_y += rotated.height + 5
    
    # Convert back to OpenCV frame
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

def apply_thumbnail_overlay(video_path, title_text):
    # Select a random neon color for this video
    random_color = random.choice(NEON_COLORS)
    
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error opening video: {video_path}")
        return
    
    fps = cap.get(cv2.CAP_PROP_FPS)
    frames_to_modify = int(0.5 * fps)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    
    # Create temp output
    temp_output = video_path + '.temp.mp4'
    out = cv2.VideoWriter(temp_output, fourcc, fps, (width, height))

    frame_count = 0
    if tqdm:
        with tqdm(total=frames_to_modify, desc="Applying thumbnail") as pbar:
            while frame_count < frames_to_modify:
                ret, frame = cap.read()
                if not ret:
                    break
                frame = add_neon_text(frame, title_text, font, random_color)
                out.write(frame)
                frame_count += 1
                pbar.update(1)
    else:
        while frame_count < frames_to_modify:
            ret, frame = cap.read()
            if not ret:
                break
            frame = add_neon_text(frame, title_text, font, random_color)
            out.write(frame)
            frame_count += 1
    
    # Process remaining frames without modification
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        out.write(frame)

    cap.release()
    out.release()
    
    # Preserve audio by muxing with original if it has audio
    if has_audio(video_path):
        try:
            temp_final = video_path + '.final.mp4'
            result = subprocess.run(['ffmpeg', '-i', temp_output, '-i', video_path, '-c', 'copy', '-map', '0:v', '-map', '1:a', '-y', temp_final], check=True, capture_output=True, text=True)
            os.replace(temp_final, video_path)
            os.remove(temp_output)  # Remove the temp video without audio
            print(f"Thumbnail applied and audio preserved for: {os.path.basename(video_path)}")
        except subprocess.CalledProcessError as e:
            print(f"Warning: Could not preserve audio for {os.path.basename(video_path)}")
            # Fallback: just replace with temp_output
            os.replace(temp_output, video_path)
    else:
        os.replace(temp_output, video_path)
        print(f"Thumbnail applied for: {os.path.basename(video_path)}")

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
	if tqdm:
		with tqdm(total=len(audio_paths), desc="Processing videos") as pbar:
			for a in audio_paths:
				target_video, matched = find_matching_video(a, video_paths)
				if not target_video:
					print(f"Skip {a}: no video available")
					pbar.update(1)
					continue
				dur = probe_duration(a)
				if not dur or dur <= 0:
					print(f"Skip {a}: could not determine audio duration")
					pbar.update(1)
					continue
				out = build_output_name(a)
				print(f"Mux: audio='{os.path.basename(a)}' ({dur:.2f}s) + video='{os.path.basename(target_video)}'{' [matched]' if matched else ''} -> {os.path.basename(out)}")
				try:
					mux_looped(target_video, a, out, dur)
					successes.append((a, target_video, matched))
				except ffmpeg.Error as e:
					print(f"FFmpeg failed for {a}: {e}")
				pbar.update(1)
	else:
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
			# Delete all videos that were used in processing
			vids = {v for _, v, _ in successes}
			for v in vids:
				try:
					os.remove(v)
					print(f"Deleted video: {os.path.basename(v)}")
				except Exception as de:
					print(f"Could not delete video {v}: {de}")


if __name__ == "__main__":
	main()
