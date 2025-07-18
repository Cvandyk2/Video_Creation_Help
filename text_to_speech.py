import os
from gtts import gTTS

# === Tip Jar ===
"https://www.paypal.com/paypalme/chancevandyke"

# 👇 Replace with your .txt filename
TEXT_FILE_NAME = "video.txt"
OUTPUT_NAME = "speech.mp3"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TEXT_FILE_PATH = os.path.join(SCRIPT_DIR, TEXT_FILE_NAME)

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
    output_path = f"{filename}.mp3"

    text_to_speech(text, output_path)

if __name__ == "__main__":
    main()
