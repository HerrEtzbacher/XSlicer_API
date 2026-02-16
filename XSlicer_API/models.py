from sqlalchemy import Column, Integer, String, Float, DateTime, Table, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import datetime

Base = declarative_base()

user_swords = Table(
    "user_swords",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("sword_id", Integer, ForeignKey("swords.id"), primary_key=True)
)

class GameUser(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String)
    password = Column(String)
    credit = Column(Integer)

    swords = relationship("Sword", secondary=user_swords, back_populates="owners")


class GameSong(Base):
    __tablename__ = "songs"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String)

class GameStat(Base):
    __tablename__ = "game_stats"

    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(String, index=True)
    score = Column(Integer)
    level = Column(Integer)
    time_played = Column(Float)  
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Sword(Base):
    __tablename__ = "swords"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    price = Column(Float)

    # Relationship: Ermöglicht den Zugriff auf Besitzer via sword.owners
    owners = relationship("GameUser", secondary=user_swords, back_populates="swords")

