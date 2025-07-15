import time
import subprocess
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

# ==== SETTINGS ====
CHROMEDRIVER = "/opt/homebrew/bin/chromedriver"  # Update this
URL = "url here"  # copy and paste public url here
VIDEO_OUT    = "video.mp4"
SCREEN_DEVICE   = "2:none"                        # replace “2” with your screen index
VIDEO_SIZE = "1440x900"                        # <-- Your screen resolution

# ==== LAUNCH CHROME FULLSCREEN ====
options = webdriver.ChromeOptions()
options.add_argument("--start-fullscreen")    # Opens Chrome in fullscreen mode
service = Service(CHROMEDRIVER)
driver = webdriver.Chrome(service=service, options=options)
driver.get(URL)
time.sleep(3)  # Wait for page load

# ==== START SCREEN RECORDING WITH FFMPEG ====
ffmpeg_cmd = [
    "ffmpeg",
    "-y",                            # overwrite output file if exists
    "-f", "avfoundation",
    "-framerate", "60",              # capture 60 fps for smoothness
    "-video_size", VIDEO_SIZE,
    "-i", SCREEN_DEVICE,             # your screen device
    "-vcodec", "libx264",
    "-preset", "veryfast",
    "-crf", "18",
    "-pix_fmt", "yuv420p",
    VIDEO_OUT
]

print("Starting screen recording...")
ffmpeg_proc = subprocess.Popen(ffmpeg_cmd)

try:
    # ==== SMOOTH SCROLL WITH JS ====
    smooth_scroll_js = """
    const pxPerFrame = 2;
    function step() {
        window.scrollBy(0, pxPerFrame);
        if (window.scrollY + window.innerHeight < document.body.scrollHeight) {
            window.requestAnimationFrame(step);
        }
    }
    step();
    """
    driver.execute_script(smooth_scroll_js)

    # Wait long enough for scrolling to finish
    scroll_height = driver.execute_script("return document.body.scrollHeight - window.innerHeight")
    estimated_duration = (scroll_height / 2) * 0.016  # pxPerFrame=2, ~16ms per frame + buffer
    time.sleep(estimated_duration)

finally:
    # ==== CLEANUP ====
    print("Stopping screen recording...")
    ffmpeg_proc.terminate()
    driver.quit()
    print(f"Video saved as {VIDEO_OUT}")
