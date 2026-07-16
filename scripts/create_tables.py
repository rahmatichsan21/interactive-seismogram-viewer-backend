from app.core.database import Base, engine

# Import model agar SQLAlchemy mengenali tabel
from app.models.waveform import WaveformRecord


print("Creating database tables...")

Base.metadata.create_all(bind=engine)

print("Database tables created successfully!")