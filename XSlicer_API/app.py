from fastapi import FastAPI, Query
import yt_dlp
import os
import shutil
import librosa
import numpy as np

app = FastAPI()

ffmpeg_path = shutil.which("ffmpeg") or os.getenv("FFMPEG_PATH")
if ffmpeg_path is None:
    raise RuntimeError(
        "FFmpeg not found. Please install FFmpeg and ensure it's in your PATH, "
        "or set the FFMPEG_PATH environment variable."
    )

OUTPUT_DIR = os.path.join(os.getcwd(), "downloads")
os.makedirs(OUTPUT_DIR, exist_ok=True)

ydl_opts = {
    "format": "bestaudio/best",
    "ffmpeg_location": ffmpeg_path,
    "outtmpl": os.path.join(OUTPUT_DIR, "%(title)s.%(ext)s"),
    "noplaylist": True,
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

def analyze_rhythm(file_path):
    print("Analysing audio")
    y, sr = librosa.load(file_path, sr=None) 

    # Tempo (BPM) and beat frames
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units='frames')
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    # Onset envelope for rhythmic intensity
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_times = librosa.times_like(onset_env, sr=sr)

    # tempogram (time-varying tempo)
    tempogram = librosa.feature.tempogram(onset_envelope=onset_env, sr=sr)

    rhythm_info = {
        "tempo_bpm": float(tempo),
        "num_beats": int(len(beat_times)),
        "beat_times_sec": beat_times.tolist(),
        "onset_times_sec": onset_times.tolist(),
        "tempogram_shape": tempogram.shape,
        "tempogram_mean": tempogram.mean(axis=1).tolist(), 
    }

    print(rhythm_info)

    return rhythm_info

@app.post("/process_link")
def process_link(link: str = Query(..., description="URL to process")):

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(link, download=True)
        filename = ydl.prepare_filename(info_dict)
        audio_file = os.path.splitext(filename)[0] + ".mp3"

    if not os.path.exists(audio_file):
        return {"error": "Audio file not found after download."}

    rhythm_data = analyze_rhythm(audio_file)
    return {"link": link, "rhythm_analysis": rhythm_data}
