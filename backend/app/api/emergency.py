"""
Emergency API — trigger, update, and list emergency events.

POST /emergency/trigger
GET  /emergency
GET  /emergency/{event_id}
PUT  /emergency/{event_id}
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.emergency import (
    EmergencyEventResponse,
    EmergencyTriggerRequest,
    EmergencyUpdateRequest,
)
from app.services.emergency_service import EmergencyService

router = APIRouter(prefix="/emergency", tags=["emergency"])


def _event_to_response(event, service: EmergencyService) -> EmergencyEventResponse:
    """Convert ORM event to response schema."""
    return EmergencyEventResponse(
        id=event.id,
        trigger_text=event.trigger_text,
        status=event.status,
        severity=event.severity,
        contacts=service.parse_contacts(event),
        notes=event.notes,
        created_at=event.created_at,
        updated_at=event.updated_at,
        resolved_at=event.resolved_at,
    )


@router.post("/trigger", response_model=EmergencyEventResponse)
def trigger_emergency(
    body: EmergencyTriggerRequest,
    db: Session = Depends(get_db),
):
    """Trigger the emergency assistance workflow (simulated)."""
    service = EmergencyService(db)
    event = service.trigger(
        trigger_text=body.trigger_text,
        severity=body.severity,
    )
    return _event_to_response(event, service)


@router.get("", response_model=list[EmergencyEventResponse])
def list_emergencies(db: Session = Depends(get_db)):
    """List all emergency events."""
    service = EmergencyService(db)
    events = service.get_all()
    return [_event_to_response(e, service) for e in events]


@router.get("/{event_id}", response_model=EmergencyEventResponse)
def get_emergency(event_id: int, db: Session = Depends(get_db)):
    """Get a specific emergency event."""
    service = EmergencyService(db)
    event = service.get_by_id(event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Emergency event not found")
    return _event_to_response(event, service)


@router.put("/{event_id}", response_model=EmergencyEventResponse)
def update_emergency(
    event_id: int,
    body: EmergencyUpdateRequest,
    db: Session = Depends(get_db),
):
    """Update the status of an emergency event."""
    service = EmergencyService(db)
    event = service.update_status(
        event_id=event_id,
        new_status=body.status,
        notes=body.notes,
    )
    if event is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid status transition or event not found",
        )
    return _event_to_response(event, service)
