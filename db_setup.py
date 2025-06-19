# db_setup.py
from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(String, primary_key=True)  # LINE user_id
    name = Column(String)
    usage = Column(Integer, default=0)
    paid_quota = Column(Integer, default=5)
    slip_file = Column(String)
    last_uploaded = Column(DateTime)

class Log(Base):
    __tablename__ = 'logs'
    id = Column(Integer, primary_key=True)
    line_id = Column(String)
    action = Column(String)
    detail = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)

# สร้างฐานข้อมูล
engine = create_engine('sqlite:///db.sqlite')
Base.metadata.create_all(engine)
