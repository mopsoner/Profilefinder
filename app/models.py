from datetime import datetime
from sqlalchemy import String, Float, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

class Job(Base):
    __tablename__="jobs"
    id: Mapped[int]=mapped_column(primary_key=True)
    city: Mapped[str]=mapped_column(String(120))
    latitude: Mapped[float]=mapped_column(Float)
    longitude: Mapped[float]=mapped_column(Float)
    radius: Mapped[int]=mapped_column()
    types: Mapped[str]=mapped_column(Text)
    max_results: Mapped[int]=mapped_column(default=20)
    rings: Mapped[int]=mapped_column(default=1)
    status: Mapped[str]=mapped_column(String(20),default="queued")
    total_found: Mapped[int]=mapped_column(default=0)
    total_filtered: Mapped[int]=mapped_column(default=0)
    error: Mapped[str|None]=mapped_column(Text,nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
    started_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    finished_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True)

class Lead(Base):
    __tablename__="leads"
    id: Mapped[int]=mapped_column(primary_key=True)
    place_id: Mapped[str]=mapped_column(String(255),unique=True,index=True)
    name: Mapped[str]=mapped_column(String(255))
    business_type: Mapped[str|None]=mapped_column(String(80),nullable=True)
    city: Mapped[str|None]=mapped_column(String(120),nullable=True)
    address: Mapped[str|None]=mapped_column(Text,nullable=True)
    phone: Mapped[str|None]=mapped_column(String(80),nullable=True)
    phone_digits: Mapped[str|None]=mapped_column(String(32),nullable=True)
    whatsapp_url: Mapped[str|None]=mapped_column(Text,nullable=True)
    website: Mapped[str|None]=mapped_column(Text,nullable=True)
    reviews_count: Mapped[int]=mapped_column(default=0)
    rating: Mapped[float|None]=mapped_column(Float,nullable=True)
    latitude: Mapped[float|None]=mapped_column(Float,nullable=True)
    longitude: Mapped[float|None]=mapped_column(Float,nullable=True)
    score: Mapped[int]=mapped_column(default=0)
    google_activity_at: Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
    first_seen_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
    updated_at: Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)

class JobLead(Base):
    __tablename__="job_leads"
    id: Mapped[int]=mapped_column(primary_key=True)
    job_id: Mapped[int]=mapped_column(ForeignKey("jobs.id"))
    lead_id: Mapped[int]=mapped_column(ForeignKey("leads.id"))
    __table_args__=(UniqueConstraint("job_id","lead_id"),)
