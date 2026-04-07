from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    presentations = relationship("Presentation", back_populates="user")


class ColorPalette(Base):
    __tablename__ = "color_palettes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    primary_color: Mapped[str] = mapped_column(String(7), nullable=False)
    secondary_color: Mapped[str] = mapped_column(String(7), nullable=False)
    accent_color: Mapped[str] = mapped_column(String(7), nullable=False)
    background_color: Mapped[str] = mapped_column(String(7), nullable=False)


class Presentation(Base):
    __tablename__ = "presentations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    configuration_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user = relationship("User", back_populates="presentations")
    tasks = relationship("TaskStatus", back_populates="presentation")


class TaskStatus(Base):
    __tablename__ = "task_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    presentation_id: Mapped[int] = mapped_column(ForeignKey("presentations.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("Queued", "Processing", "Completed", "Failed", name="task_status_enum"),
        default="Queued",
        nullable=False,
    )
    message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    presentation = relationship("Presentation", back_populates="tasks")
