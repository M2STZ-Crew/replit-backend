# app/models/enums.py
"""
enums.py – Shared enumerations used across models and schemas.
"""

from enum import Enum


class IncidentStatus(str, Enum):
    PENDING    = "PENDING"
    VERIFIED   = "VERIFIED"
    DISMISSED  = "DISMISSED"
    DISPATCHED = "DISPATCHED"
    CONTROLLED = "CONTROLLED"
    RESOLVED   = "RESOLVED"


class IncidentSeverity(str, Enum):
    UNKNOWN  = "UNKNOWN"
    LOW      = "LOW"
    MEDIUM   = "MEDIUM"
    HIGH     = "HIGH"
    CRITICAL = "CRITICAL"


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class AssignmentStatus(str, Enum):
    EN_ROUTE  = "EN_ROUTE"
    ON_SCENE  = "ON_SCENE"
    COMPLETED = "COMPLETED"


class UserRole(str, Enum):
    CITIZEN     = "citizen"
    DISPATCHER  = "dispatcher"
    RESPONDER   = "responder"
    SUB_ADMIN   = "sub_admin"
    SUPER_ADMIN = "super_admin"