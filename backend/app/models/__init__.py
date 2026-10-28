"""
ORM model registry.

Import all models here so that Base.metadata.create_all() discovers every table.
"""

from app.models.device import Device
from app.models.emergency import EmergencyEvent
from app.models.interaction import ActivityLog, Interaction

__all__ = ["Device", "Interaction", "ActivityLog", "EmergencyEvent"]
