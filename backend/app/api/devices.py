"""Device API routes."""

import json

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.device import (
    DeviceCommandRequest,
    DeviceListResponse,
    DeviceResponse,
    DeviceStateUpdate,
)
from app.services.device_service import DeviceService
from app.services.voice_auth_service import VoiceAuthService

router = APIRouter(prefix="/devices", tags=["devices"])
_voice_auth_service = VoiceAuthService()


def _device_to_response(device) -> DeviceResponse:
    """Convert an ORM Device to a response schema."""
    return DeviceResponse(
        id=device.id,
        name=device.name,
        device_type=device.device_type,
        location=device.location,
        state=device.state,
        supported_actions=json.loads(device.supported_actions),
        is_active=device.is_active,
        updated_at=device.updated_at,
    )


@router.get("", response_model=DeviceListResponse)
def list_devices(db: Session = Depends(get_db)):
    """List all active devices and their current states."""
    service = DeviceService(db)
    devices = service.list_devices()
    items = [_device_to_response(d) for d in devices]
    return DeviceListResponse(devices=items, count=len(items))


@router.get("/{device_id}", response_model=DeviceResponse)
def get_device(device_id: str, db: Session = Depends(get_db)):
    """Retrieve a single device by ID."""
    service = DeviceService(db)
    device = service.get_device(device_id)
    if device is None:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' not found")
    return _device_to_response(device)


@router.post("/{device_id}/command", response_model=DeviceStateUpdate)
def command_device(
    device_id: str,
    body: DeviceCommandRequest,
    authorization: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
):
    """
    Send a direct command to a device.

    Security requirement (TEST 7):
      Direct API requests attempting to control a device without authentication
      must be rejected with HTTP 401 Unauthorized.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()

    valid, _ = _voice_auth_service.verify_session_token(token) if token else (False, None)
    if not valid:
        raise HTTPException(
            status_code=401,
            detail="Authentication required: Direct device control without authentication is forbidden.",
        )

    service = DeviceService(db)
    result = service.execute_action(device_id, body.action)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return DeviceStateUpdate(**result)
