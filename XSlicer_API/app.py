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
import requests
from fastapi.responses import StreamingResponse
import io
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select
from pydantic import BaseModel
from db import get_db
from models import GameStat
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class GameStatCreate(BaseModel):
    player_id: str
    score: int
    level: int
    time_played: float

ffmpeg_path = shutil.which("ffmpeg") or os.getenv("FFMPEG_PATH")
OUTPUT_DIR = os.path.join(os.getcwd(), "songs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Helper to get the folder for a specific video
def get_song_dir(video_id: str):
    return os.path.join(OUTPUT_DIR, video_id)

# --- LOGIC ---
def analyze_rhythm(file_path):
    print(f"Analyzing: {file_path}")
    y, sr = librosa.load(file_path, sr=None)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    
    return {
        "tempo_bpm": float(tempo),
        "num_beats": int(len(beat_times)),
        "beat_times_sec": beat_times.tolist(),
    }

@app.post("/process_link")
def process_link(link: str = Query(..., description="URL to process")):
    # 1. Get basic info first to check cache
    with yt_dlp.YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
        try:
            info = ydl.extract_info(link, download=False)
            video_id = info.get("id")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Link: {str(e)}")

    song_dir = get_song_dir(video_id)
    metadata_path = os.path.join(song_dir, "metadata.json")

    # 2. SERVER-SIDE CACHE CHECK
    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            return {"message": "Loaded from cache", "metadata": json.load(f)}

    # 3. DOWNLOAD IF NOT CACHED
    os.makedirs(song_dir, exist_ok=True)
    temp_ydl_opts = {
        "format": "bestaudio/best",
        "ffmpeg_location": ffmpeg_path,
        "outtmpl": os.path.join(song_dir, "audio.%(ext)s"), # Fixed name inside folder
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}],
        "quiet": True
    }

    with yt_dlp.YoutubeDL(temp_ydl_opts) as ydl:
        ydl.download([link])

    audio_file = os.path.join(song_dir, "audio.mp3")
    rhythm_data = analyze_rhythm(audio_file)

    metadata = {
        "id": video_id,
        "title": info.get("title", "Unknown"),
        "artist": info.get("uploader", "Unknown"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "rhythm_analysis": rhythm_data,
        "file_path": audio_file 
    }

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=4)

    return {"message": "Processed successfully", "metadata": metadata}

@app.get("/songs/{video_id}/file")
def get_song_file(video_id: str):
    audio_path = os.path.join(get_song_dir(video_id), "audio.mp3")
    if os.path.exists(audio_path):
        return FileResponse(audio_path, media_type="audio/mpeg", filename=f"{video_id}.mp3")
    raise HTTPException(status_code=404, detail="Audio not found")

@app.get("/proxy_image")
async def proxy_image(url: str):
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=5)
    return StreamingResponse(io.BytesIO(resp.content), media_type="image/jpeg")

@app.post("/stats")
async def create_stat(stat: GameStatCreate, db: AsyncSession = Depends(get_db)):
    new_stat = GameStat(**stat.dict())
    db.add(new_stat)
    await db.commit()
    return {"status": "success"}

@app.get("/stats/{player_id}")
async def get_stats(player_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GameStat).where(GameStat.player_id == player_id)
    )
    stats = result.scalars().all()
    return stats

@app.get("/get_metadata")
def get_metadata_only(link: str = Query(..., description="YouTube URL to fetch metadata from")):
    metadata_opts = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "skip_download": True,
    }

    try:
        with yt_dlp.YoutubeDL(metadata_opts) as ydl:

            info_dict = ydl.extract_info(link, download=False)

            metadata = {
                "id": info_dict.get("id", "UnknownID"),
                "title": info_dict.get("title", "Unknown Title"),
                "artist": info_dict.get("uploader", "Unknown Artist"),
                "duration": info_dict.get("duration", 0),
                "thumbnail_url": info_dict.get("thumbnail"),
                "upload_date": info_dict.get("upload_date", ""),
                "link": link,
                "analyzed_at": None, 
                "rhythm_analysis": None,
                "file_path": None
            }

            return {
                "message": "Metadata fetched successfully.",
                "metadata": metadata
            }
            
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch metadata: {str(e)}")