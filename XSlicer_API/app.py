from fastapi import FastAPI, Query
import yt_dlp
import os
import shutil

app = FastAPI()

# Automatically find ffmpeg if installed and in PATH, or allow user to set it via environment variable
ffmpeg_path = shutil.which("ffmpeg") or os.getenv("FFMPEG_PATH")

if ffmpeg_path is None:
    raise RuntimeError(
        "FFmpeg not found. Please install FFmpeg and ensure it's in your PATH, "
        "or set the FFMPEG_PATH environment variable."
    )

# output directory (within the project folder)
OUTPUT_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(OUTPUT_DIR, exist_ok=True)

ydl_opts = {
    "format": "bestaudio/best",
    "ffmpeg_location": ffmpeg_path,
    "outtmpl": os.path.join(OUTPUT_DIR, "%(title)s.%(ext)s"),
    "postprocessors": [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }
    ],
}

@app.get("/")
def home():
    return {"message": "Song Processing"}

@app.post("/process_link")
def process_link(link: str = Query(..., description="URL to process")):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([link])
    return {"received_link": link}
