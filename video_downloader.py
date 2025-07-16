import yt_dlp

# === Tip Jar ===
"https://www.paypal.com/paypalme/chancevandyke"

# === 📋 PASTE YOUR VIDEO URLs HERE ===
VIDEO_URLS = [
    "url"
    # Add URLs from other supported sites here
]
# =======================================


# === 📋 Enter Folder Name HERE ===
output_folder = "other"
# =======================================

def download_videos(urls, output_folder, quiet=False, allow_playlist=False):
    ydl_opts = {
        'outtmpl': f'{output_folder}/%(upload_date)s_%(title)s.%(ext)s',
        'format': 'bestvideo+bestaudio/best',  # simpler, more generic format selector
        'merge_output_format': 'mp4',
        'noplaylist': not allow_playlist,
        'quiet': quiet,
        'no_warnings': True,
        'ignoreerrors': True,  # continue downloading others if one fails
        'retries': 2,  # retry failed downloads up to 2 times
        'progress_hooks': [lambda d: print(f"{d['status'].capitalize()}: {d.get('filename', '')}") if d['status'] in ['downloading', 'finished'] else None],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for url in urls:
            try:
                print(f"⬇️ Downloading: {url}")
                ydl.download([url])
            except Exception as e:
                print(f"❌ Error downloading {url}: {e}")


if __name__ == "__main__":
    download_videos(VIDEO_URLS, output_folder, quiet=False, allow_playlist=False)
