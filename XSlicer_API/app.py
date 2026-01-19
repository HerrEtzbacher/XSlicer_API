from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse
import yt_dlp
import os
import shutil
import librosa
import numpy as np
import json
from datetime import datetime
from typing import List
from sqlalchemy import select
from pydantic import BaseModel
from db import get_db
from models import GameStat
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

app = FastAPI()

class GameStatCreate(BaseModel):
    player_id: str
    score: int
    level: int
    time_played: float

ffmpeg_path = shutil.which("ffmpeg") or os.getenv("FFMPEG_PATH")
if ffmpeg_path is None:
    raise RuntimeError(
        "FFmpeg not found. Please install FFmpeg and ensure it's in your PATH, "
        "or set the FFMPEG_PATH environment variable."
    )

OUTPUT_DIR = os.path.join(os.getcwd(), "songs")
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
    return {"message": "XSlicer Song API"}

def analyze_rhythm(file_path):
    print("Analysing audio...")
    y, sr = librosa.load(file_path, sr=None)

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onset_times = librosa.times_like(onset_env, sr=sr)
    tempogram = librosa.feature.tempogram(onset_envelope=onset_env, sr=sr)

    rhythm_info = {
        "tempo_bpm": float(tempo),
        "num_beats": int(len(beat_times)),
        "beat_times_sec": beat_times.tolist(),
        "onset_times_sec": onset_times.tolist(),
        "tempogram_shape": tempogram.shape,
        "tempogram_mean": tempogram.mean(axis=1).tolist(),
    }

    return rhythm_info

@app.post("/process_link")
def process_link(link: str = Query(..., description="URL to process")):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(link, download=True)
        filename = ydl.prepare_filename(info_dict)
        title = info_dict.get("title", "UnknownTitle").strip()
        artist = info_dict.get("uploader", "UnknownArtist")
        upload_date = info_dict.get("upload_date", None)
        duration = info_dict.get("duration", None)
        thumbnail = info_dict.get("thumbnail", None)

    audio_file = os.path.splitext(filename)[0] + ".mp3"

    if not os.path.exists(audio_file):
        return {"error": "Audio file not found after download."}

    song_dir = os.path.join(OUTPUT_DIR, title)
    os.makedirs(song_dir, exist_ok=True)

    dest_audio_path = os.path.join(song_dir, f"{title}.mp3")
    if not os.path.exists(dest_audio_path):
        shutil.move(audio_file, dest_audio_path)

    rhythm_data = analyze_rhythm(dest_audio_path)

    metadata = {
        "id": title.replace(" ", "_"),
        "title": title,
        "artist": artist,
        "duration": duration,
        "upload_date": upload_date,
        "link": link,
        "analyzed_at": datetime.utcnow().isoformat(),
        "rhythm_analysis": rhythm_data,
        "file_path": dest_audio_path,
        "thumbnail": thumbnail
    }

    metadata_path = os.path.join(song_dir, "metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4)

    return {
        "message": f"Processed '{title}' successfully.",
        "metadata_path": metadata_path,
        "metadata": metadata
    }

@app.get("/songs")
def list_songs() -> List[dict]:
    """Returns a list of all songs (metadata summaries)."""
    songs = []
    for folder in os.listdir(OUTPUT_DIR):
        song_dir = os.path.join(OUTPUT_DIR, folder)
        metadata_path = os.path.join(song_dir, "metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                songs.append({
                    "id": data.get("id"),
                    "title": data.get("title"),
                    "artist": data.get("artist"),
                    "duration": data.get("duration"),
                    "tempo_bpm": data.get("rhythm_analysis", {}).get("tempo_bpm"),
                })
    return songs

@app.get("/songs/{song_id}")
def get_song_metadata(song_id: str):
    """Return detailed metadata and local file path for a specific song."""
    for folder in os.listdir(OUTPUT_DIR):
        song_dir = os.path.join(OUTPUT_DIR, folder)
        metadata_path = os.path.join(song_dir, "metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("id") == song_id:
                    return data
    raise HTTPException(status_code=404, detail=f"Song with ID '{song_id}' not found.")


@app.get("/songs/{song_id}/file")
def get_song_file(song_id: str):
    """Return the MP3 file for download."""
    for folder in os.listdir(OUTPUT_DIR):
        song_dir = os.path.join(OUTPUT_DIR, folder)
        metadata_path = os.path.join(song_dir, "metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data.get("id") == song_id:
                    mp3_path = data.get("file_path")
                    if os.path.exists(mp3_path):
                        return FileResponse(mp3_path, media_type="audio/mpeg", filename=os.path.basename(mp3_path))
    raise HTTPException(status_code=404, detail=f"Audio file for '{song_id}' not found.")

@app.post("/stats/")
async def save_stat(stat: GameStatCreate, db: AsyncSession = Depends(get_db)):
    new_stat = GameStat(
        player_id=stat.player_id,
        score=stat.score,
        level=stat.level,
        time_played=stat.time_played,
    )
    db.add(new_stat)
    await db.commit()
    await db.refresh(new_stat)
    return {"status": "ok", "id": new_stat.id}

@app.get("/stats/{player_id}")
async def get_stats(player_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GameStat).where(GameStat.player_id == player_id)
    )
    stats = result.scalars().all()
    return stats

@app.post("/stats", response_model=None)
async def create_stat(stat: GameStatCreate, db: AsyncSession = Depends(get_db)):
    """
    Adds a new game statistic entry to the database.
    """
    try:
        new_stat = GameStat(
            player_id=stat.player_id,
            score=stat.score,
            level=stat.level,
            time_played=stat.time_played,
        )
        
        db.add(new_stat)
        await db.commit()
        await db.refresh(new_stat)  
        
        return {
            "status": "success",
            "data": {
                "id": new_stat.id,
                "player_id": new_stat.player_id,
                "score": new_stat.score,
                "level": new_stat.level,
                "time_played": new_stat.time_played,
                "created_at": new_stat.created_at
            }
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))