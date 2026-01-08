import os
from gtts import gTTS

# 👇 Replace with your .txt filename
TEXT_FILE_NAME = "Speechify_Video.txt"
OUTPUT_NAME = "speech.mp3"

# Root and I/O settings
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)

# Toggle this to True to save into coding_audio; default saves into Audio
USE_CODING_AUDIO = True

# Determine output directory based on the setting and ensure it exists
OUTPUT_DIR = os.path.join(ROOT_DIR, "coding_audio" if USE_CODING_AUDIO else "Audio")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Prefer text file next to this script; if missing, fall back to Audio/video.txt
TEXT_FILE_PATH = os.path.join(SCRIPT_DIR, TEXT_FILE_NAME)
if not os.path.exists(TEXT_FILE_PATH):
    alt_text_path = os.path.join(ROOT_DIR, "Audio", TEXT_FILE_NAME)
    if os.path.exists(alt_text_path):
        TEXT_FILE_PATH = alt_text_path
    else:
        raise FileNotFoundError(f"Could not find '{TEXT_FILE_NAME}' in {SCRIPT_DIR} or {os.path.join(ROOT_DIR, 'Audio')}")

def read_text_file(path):
    with open(path, 'r', encoding='utf-8') as file:
        return file.read()

def text_to_speech(text, output_file=OUTPUT_NAME, lang="en"):
    tts = gTTS(text=text, lang=lang)
    tts.save(output_file)
    print(f"✅ Audio saved to {output_file}")

def main():
    text = read_text_file(TEXT_FILE_PATH)
    print(f"✅ Extracted text ({len(text)} characters).")

    # 🔠 Prompt user for output name
    filename = input("Enter a name for the audio file (without .mp3) [default: video_audio]: ").strip()
    if not filename:
        filename = "video_audio"
    output_path = os.path.join(OUTPUT_DIR, f"{filename}.mp3")

    text_to_speech(text, output_path)

if __name__ == "__main__":
    main()
