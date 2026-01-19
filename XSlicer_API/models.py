from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
import datetime

Base = declarative_base()

class GameStat(Base):
    __tablename__ = "game_stats"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(String, index=True)
    score = Column(Integer)
    level = Column(Integer)
    time_played = Column(Float)  
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
