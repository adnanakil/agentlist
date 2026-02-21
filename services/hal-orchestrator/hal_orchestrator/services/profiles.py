"""User profile CRUD (Postgres)."""

from __future__ import annotations

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ag_db.models import HalUserProfile

log = structlog.get_logger()


async def get_profile(session: AsyncSession, phone: str) -> dict:
    """Get a user's profile, creating one if it doesn't exist."""
    stmt = select(HalUserProfile).where(HalUserProfile.phone == phone)
    result = await session.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        return {
            "phone": phone,
            "name": None,
            "email": None,
            "onboarded": False,
            "google_connected": False,
            "notes": None,
        }

    return {
        "phone": profile.phone,
        "name": profile.name,
        "email": profile.email,
        "onboarded": profile.onboarded,
        "google_connected": profile.google_connected,
        "notes": profile.notes,
    }


async def update_profile(session: AsyncSession, phone: str, **fields: object) -> dict:
    """Update a user's profile, creating one if it doesn't exist."""
    stmt = select(HalUserProfile).where(HalUserProfile.phone == phone)
    result = await session.execute(stmt)
    profile = result.scalar_one_or_none()

    if profile is None:
        profile = HalUserProfile(phone=phone)
        session.add(profile)

    for key, value in fields.items():
        if hasattr(profile, key) and key not in ("id", "phone", "created_at", "updated_at"):
            setattr(profile, key, value)

    await session.flush()

    return {
        "phone": profile.phone,
        "name": profile.name,
        "email": profile.email,
        "onboarded": profile.onboarded,
        "google_connected": profile.google_connected,
        "notes": profile.notes,
    }
