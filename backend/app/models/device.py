"""Device ORM model — represents a controllable smart-home device."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Device(Base):
    """A virtual smart-home device (light, fan, etc.)."""

    __tablename__ = "devices"

    # Use a human-readable slug as the primary key (e.g. "bedroom_light")
    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    # Display name shown in the UI (e.g. "Bedroom Light")
    name: Mapped[str] = mapped_column(String(128), nullable=False)

    # Category: "light", "fan", "thermostat", etc.
    device_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # Room / area: "bedroom", "living_room", etc.
    location: Mapped[str] = mapped_column(String(64), nullable=False)

    # Current state — typically "ON" or "OFF"
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="OFF")

    # JSON list of supported actions, e.g. '["ON", "OFF"]'
    supported_actions: Mapped[str] = mapped_column(
        Text, nullable=False, default='["ON", "OFF"]'
    )

    # Whether this device is available in the system
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return f"<Device {self.id} state={self.state}>"
