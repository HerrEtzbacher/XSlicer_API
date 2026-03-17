from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, insert, and_, func
from pydantic import BaseModel
import yt_dlp, os, shutil, librosa, numpy as np, json, requests, io
from db import get_db
from models import GameStat, GameSong, GameUser, Sword, user_swords

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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
OUTPUT_DIR = os.path.join(os.getcwd(), "songs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def get_song_dir(video_id: str):
    return os.path.join(OUTPUT_DIR, video_id)

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
    with yt_dlp.YoutubeDL({'quiet': True, 'noplaylist': True}) as ydl:
        try:
            info = ydl.extract_info(link, download=False)
            video_id = info.get("id")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid Link: {str(e)}")

    song_dir = get_song_dir(video_id)
    metadata_path = os.path.join(song_dir, "metadata.json")

    if os.path.exists(metadata_path):
        with open(metadata_path, "r", encoding="utf-8") as f:
            return {"message": "Loaded from cache", "metadata": json.load(f)}

    os.makedirs(song_dir, exist_ok=True)
    temp_ydl_opts = {
        "format": "bestaudio/best",
        "ffmpeg_location": ffmpeg_path,
        "outtmpl": os.path.join(song_dir, "audio.%(ext)s"),
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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    response = requests.get(url, headers=headers, timeout=5)
    return StreamingResponse(io.BytesIO(response.content), media_type="image/jpeg")

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
            return {"message": "Metadata fetched successfully.", "metadata": metadata}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to fetch metadata: {str(e)}")

@app.get("/stats/{player_id}")
async def get_stats(player_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GameStat).where(GameStat.player_id == player_id)
    )
    stats = result.scalars().all()
    return stats

@app.post("/song", response_model=None)
async def create_song(song: GameSongCreate, db: AsyncSession = Depends(get_db)):
    try:
        new_stat = GameSong(url=song.url)
        db.add(new_stat)
        await db.commit()
        await db.refresh(new_stat)
        return {"status": "success", "data": {"id": new_stat.id, "url": new_stat.url}}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/songs")
async def get_songs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GameSong))
    songs = result.scalars().all()
    return songs

@app.post("/user", response_model=None)
async def create_user(user: GameUserCreate, db: AsyncSession = Depends(get_db)):
    try:
        query = select(GameUser).where(GameUser.username == user.username)
        result = await db.execute(query)
        existing_user = result.scalars().first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Benutzername bereits vergeben")

        new_user = GameUser(username=user.username, password=user.password, credit=0)
        db.add(new_user)
        await db.commit()
        await db.refresh(new_user)
        return {"status": "success", "data": {"id": new_user.id, "username": new_user.username}}
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

@app.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(GameUser).where(GameUser.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User nicht gefunden")
    return {"id": user.id, "username": user.username, "credit": user.credit}

@app.post("/stats", response_model=None)
async def create_stat(stat: GameStatCreate, db: AsyncSession = Depends(get_db)):
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
    query = select(GameStat).where(
        and_(
            GameStat.player_id == player_id,
            GameStat.level == level
        )
    )
    result = await db.execute(query)
    stats = result.scalars().all()
    return stats

@app.get("/highscores")
async def get_highscores(limit: int = 10, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(GameStat.player_id, func.sum(GameStat.score).label("total_score"))
        .group_by(GameStat.player_id)
        .order_by(func.sum(GameStat.score).desc())
        .limit(limit)
    )
    return [{"player_id": r.player_id, "total_score": r.total_score} for r in result.all()]

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
        return {"status": "success", "message": f"'{sword.name}' gekauft für {sword.price} Credits."}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"Datenbankfehler: {str(e)}")

@app.get("/swords")
async def get_swords(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Sword).where(True))
    swords = result.scalars().all()
    return swords

@app.get("/user/{user_id}/swords")
async def get_swords_for_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Sword)
        .join(user_swords, Sword.id == user_swords.c.sword_id)
        .where(user_swords.c.user_id == user_id)
    )
    return result.scalars().all()

@app.post("/add_sword")
async def add_sword(request: AddSwordRequest, db: AsyncSession = Depends(get_db)):
    try:
        new_sword = Sword(name=request.name, price=request.cost)
        db.add(new_sword)
        await db.commit()
        await db.refresh(new_sword)
        return {"status": "success", "data": {"id": new_sword.id, "name": new_sword.name, "cost": new_sword.price}}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/users/{user_id}/credits")
async def update_credits(user_id: int, amount: int, db: AsyncSession = Depends(get_db)):
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
