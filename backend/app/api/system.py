"""System status API route."""

import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database.session import get_db
from app.models.device import Device
from app.models.emergency import EmergencyEvent
from app.models.interaction import Interaction
from app.schemas.system import SystemStatusResponse

router = APIRouter(tags=["system"])


@router.get("/system/status", response_model=SystemStatusResponse)
def system_status(db: Session = Depends(get_db)):
    """Retrieve system health information."""
    from app.main import get_start_time

    start_time = get_start_time()

    vosk_path = settings.get_vosk_model_path()
    voice_path = settings.get_enrolled_voice_path()

    total_devices = db.query(Device).count()
    active_devices = db.query(Device).filter(Device.is_active.is_(True)).count()
    total_interactions = db.query(Interaction).count()
    active_emergencies = (
        db.query(EmergencyEvent)
        .filter(EmergencyEvent.status == "ACTIVE")
        .count()
    )

    return SystemStatusResponse(
        status="healthy",
        version="2.0.0",
        vosk_model_loaded=vosk_path.is_dir(),
        voice_enrolled=voice_path.is_file(),
        total_devices=total_devices,
        active_devices=active_devices,
        total_interactions=total_interactions,
        active_emergencies=active_emergencies,
        uptime_seconds=round(time.time() - start_time, 2) if start_time else 0,
        timestamp=datetime.now(timezone.utc),
    )
