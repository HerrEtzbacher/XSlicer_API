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
from models import Sword 
from models import user_swords
import requests
from fastapi.responses import StreamingResponse
import io
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, and_
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import update, and_
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert, and_

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
from sqlalchemy import select
from pydantic import BaseModel
from db import get_db
from models import GameStat
from models import GameSong
from models import GameUser
from models import Sword
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

app = FastAPI()

class GameStatCreate(BaseModel):
    player_id: str
    score: int
    level: int
    time_played: float

class GameSongCreate(BaseModel):
    url: str

class GameUserCreate(BaseModel):
    username: str
    password: str

class SwordBase(BaseModel):
    name: str
    price: float

    class Config:
        orm_mode = True

class BuySwordRequest(BaseModel):
    user_id: int
    sword_id: int

class AddSwordRequest(BaseModel):
    name: str
    cost: int


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
    
@app.get("/proxy_image")
async def proxy_image(url: str):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    response = requests.get(url, headers=headers, timeout=5)
    return StreamingResponse(io.BytesIO(response.content), media_type="image/jpeg")

@app.get("/stats/{player_id}")
async def get_stats(player_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GameStat).where(GameStat.player_id == player_id)
    )
    stats = result.scalars().all()
    return stats

@app.post("/song", response_model=None)
async def create_song(song: GameSongCreate, db: AsyncSession = Depends(get_db)):
    """
    Adds a new game statistic entry to the database.
    """
    try:
        new_stat = GameSong(
            url=song.url,
        )
        
        db.add(new_stat)
        await db.commit()
        await db.refresh(new_stat)  
        
        return {
            "status": "success",
            "data": {
                "id": new_stat.id,
                "url": new_stat.url
            }
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/songs")
async def get_songs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GameSong)
    )
    songs = result.scalars().all()
    return songs
    
@app.post("/user", response_model=None)
async def create_user(user: GameUserCreate, db: AsyncSession = Depends(get_db)):
    try:
        query = select(GameUser).where(GameUser.username == user.username)
        result = await db.execute(query)
        existing_user = result.scalars().first()

        if existing_user:
            raise HTTPException(
                status_code=400, 
                detail="Benutzername bereits vergeben"
            )

        new_stat = GameUser(
            username=user.username,
            password=user.password, 
            credit = 0,
        )
        
        db.add(new_stat)
        await db.commit()
        await db.refresh(new_stat)  
        
        return {
            "status": "success",
            "data": {
                "id": new_stat.id,
                "username": new_stat.username
            }
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
@app.get("/users")
async def get_users(username: str, password: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GameUser).where(
            and_(GameUser.username == username, GameUser.password == password)
        )
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
    
@app.get("/stats/filter")
async def get_specific_stats(player_id: str, level: int, db: AsyncSession = Depends(get_db)):
    """
    Gibt Statistiken zurück, die exakt zu player_id UND level passen.
    """
    query = select(GameStat).where(
        and_(
            GameStat.player_id == player_id,
            GameStat.level == level
        )
    )
    
    result = await db.execute(query)
    stats = result.scalars().all()
    return stats

@app.post("/users/buy_sword")
async def buy_sword(request: BuySwordRequest, db: AsyncSession = Depends(get_db)):
    sword_query = await db.execute(select(Sword).where(Sword.id == request.sword_id))
    sword = sword_query.scalars().first()
    
    if not sword:
        raise HTTPException(status_code=404, detail="Schwert nicht gefunden")

    try:
        credit_stmt = (
            update(GameUser)
            .where(GameUser.id == request.user_id)
            .where(GameUser.credit >= sword.price)
            .values(credit=GameUser.credit - sword.price)
        )
        
        result = await db.execute(credit_stmt)
        
        if result.rowcount == 0:
            raise HTTPException(
                status_code=400, 
                detail="Kauf fehlgeschlagen: User nicht gefunden oder zu wenig Credits"
            )

        check_query = select(user_swords).where(
            and_(user_swords.c.user_id == request.user_id, user_swords.c.sword_id == sword.id)
        )
        existing = await db.execute(check_query)
        if existing.first():
            await db.rollback()
            return {"message": "User besitzt dieses Schwert bereits"}

        await db.execute(
            insert(user_swords).values(user_id=request.user_id, sword_id=sword.id)
        )

        await db.commit()
        return {
            "status": "success", 
            "message": f"'{sword.name}' gekauft für {sword.price} Credits."
        }

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Datenbankfehler: {str(e)}")
    
@app.get("/swords")
async def get_swords(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Sword).where(True)
    )
    swords = result.scalars().all()
    return swords

@app.get("/user/{user_id}/swords")
async def get_swords_for_user(user_id: int, db: AsyncSession = Depends(get_db)):
    tables = await db.execute(
        select(user_swords).where(user_swords.user_id == user_id)
    )
    for table in tables:
        result += await db.execute(
            select(Sword).where(Sword.id == table.id)
        )   
    swords = result.scalars().all()
    return swords
    
@app.post("/add_sword")
async def add_sword(request: AddSwordRequest, db: AsyncSession = Depends(get_db)):
    try:
        new_stat = Sword(
            name=request.name,
            price=request.cost,
        )
        
        db.add(new_stat)
        await db.commit()
        await db.refresh(new_stat)  
        
        return {
            "status": "success",
            "data": {
                "id": new_stat.id,
                "name": new_stat.name,
                "cost": new_stat.price,
            }
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
    
    
@app.patch("/users/{user_id}/credits")
async def update_credits(user_id: int, amount: int, db: Session = Depends(get_db)):
  
    stmt = (
        update(GameUser)
        .where(GameUser.id == user_id)
        .where((GameUser.credit + amount) >= 0)
        .values(credit=GameUser.credit + amount)
    )
    
    result = await db.execute(stmt)
    await db.commit()

    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transaktion abgelehnt: User nicht gefunden oder unzureichendes Guthaben."
        )

    return {"message": "Guthaben erfolgreich aktualisiert", "delta": amount}

