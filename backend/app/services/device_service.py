"""Device service — business logic for virtual smart-home devices."""

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.interaction import ActivityLog


class DeviceService:
    """Stateless service — receives a DB session per call."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Queries ────────────────────────────────────────────────────────────

    def list_devices(self, active_only: bool = True) -> list[Device]:
        """Return all (or only active) devices."""
        query = self.db.query(Device)
        if active_only:
            query = query.filter(Device.is_active.is_(True))
        return query.order_by(Device.id).all()

    def get_device(self, device_id: str) -> Device | None:
        """Get a single device by ID."""
        return self.db.query(Device).filter(Device.id == device_id).first()

    def get_device_by_name_or_location(
        self, name: str | None = None, location: str | None = None,
        device_type: str | None = None,
    ) -> list[Device]:
        """Find devices matching partial criteria (for intent resolution)."""
        query = self.db.query(Device).filter(Device.is_active.is_(True))
        if name:
            query = query.filter(Device.name.ilike(f"%{name}%"))
        if location:
            query = query.filter(Device.location == location)
        if device_type:
            query = query.filter(Device.device_type == device_type)
        return query.all()

    # ── Commands ───────────────────────────────────────────────────────────

    def execute_action(
        self,
        device_id: str,
        action: str,
        interaction_id: int | None = None,
    ) -> dict:
        """
        Validate and execute a device action.

        Returns a dict with: device_id, action, previous_state, new_state,
        success, message.
        """
        device = self.get_device(device_id)
        if device is None:
            return {
                "device_id": device_id,
                "action": action,
                "previous_state": "UNKNOWN",
                "new_state": "UNKNOWN",
                "success": False,
                "message": f"Device '{device_id}' not found.",
            }

        if not device.is_active:
            return {
                "device_id": device_id,
                "action": action,
                "previous_state": device.state,
                "new_state": device.state,
                "success": False,
                "message": f"Device '{device.name}' is currently inactive.",
            }

        # Validate action against supported actions
        supported = json.loads(device.supported_actions)
        action_upper = action.upper()
        if action_upper not in supported:
            return {
                "device_id": device_id,
                "action": action_upper,
                "previous_state": device.state,
                "new_state": device.state,
                "success": False,
                "message": (
                    f"Action '{action_upper}' is not supported for {device.name}. "
                    f"Supported actions: {supported}"
                ),
            }

        # Check if already in the target state
        previous_state = device.state
        if previous_state == action_upper:
            # Not an error — device is already in the desired state
            self._log_activity(
                interaction_id=interaction_id,
                device_id=device_id,
                action=action_upper,
                previous_state=previous_state,
                new_state=previous_state,
                success=True,
                error_message=None,
            )
            return {
                "device_id": device_id,
                "action": action_upper,
                "previous_state": previous_state,
                "new_state": previous_state,
                "success": True,
                "message": f"{device.name} is already {action_upper}.",
            }

        # Execute the state change
        device.state = action_upper
        device.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(device)

        self._log_activity(
            interaction_id=interaction_id,
            device_id=device_id,
            action=action_upper,
            previous_state=previous_state,
            new_state=device.state,
            success=True,
            error_message=None,
        )

        return {
            "device_id": device_id,
            "action": action_upper,
            "previous_state": previous_state,
            "new_state": device.state,
            "success": True,
            "message": f"{device.name} turned {action_upper}.",
        }

    # ── Internal helpers ───────────────────────────────────────────────────

    def _log_activity(
        self,
        device_id: str,
        action: str,
        previous_state: str,
        new_state: str,
        success: bool,
        interaction_id: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Write a row to the activity_log table."""
        log = ActivityLog(
            interaction_id=interaction_id,
            device_id=device_id,
            action=action,
            previous_state=previous_state,
            new_state=new_state,
            success=success,
            error_message=error_message,
        )
        self.db.add(log)
        self.db.commit()
