"""Device API routes."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.device import (
    DeviceCommandRequest,
    DeviceListResponse,
    DeviceResponse,
    DeviceStateUpdate,
)
from app.services.device_service import DeviceService

router = APIRouter(prefix="/devices", tags=["devices"])


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
    db: Session = Depends(get_db),
):
    """
    Send a command to a device.

    This goes through backend validation (supported action check,
    state validation). In the full pipeline, voice commands also
    pass through the decision engine before reaching this layer.
    """
    service = DeviceService(db)
    result = service.execute_action(device_id, body.action)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["message"])
    return DeviceStateUpdate(**result)
