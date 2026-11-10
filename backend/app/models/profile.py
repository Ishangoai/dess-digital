"""Minutes Profiles and their immutable, versioned content."""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, JSONType


def utcnow() -> datetime:
    return datetime.now(UTC)


def str_enum(enum: type[StrEnum]) -> SAEnum:
    # Store values as VARCHAR (not a native PG enum) so adding a value needs no migration.
    return SAEnum(
        enum, native_enum=False, length=32, values_callable=lambda e: [m.value for m in e]
    )


class ProfileVersionStatus(StrEnum):
    PROPOSED = "proposed"
    REVIEWED = "reviewed"
    CONFIRMED = "confirmed"
    WITHDRAWN = "withdrawn"


class VersionOrigin(StrEnum):
    SEED = "seed"  # loaded from a profile file
    API = "api"  # posted through the API
    CUSTOMISATION = "customisation"  # future: conversational customisation (Component 2)
    FEEDBACK = "feedback"  # future: learning from edited drafts (Component 4)


class MinutesProfile(Base):
    __tablename__ = "minutes_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    # Board/committee this profile governs; None for the DESS Standard.
    body_name: Mapped[str | None] = mapped_column(String(255))
    based_on_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("minutes_profiles.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    versions: Mapped[list["MinutesProfileVersion"]] = relationship(
        back_populates="profile", order_by="MinutesProfileVersion.version_number"
    )
    based_on: Mapped["MinutesProfile | None"] = relationship(remote_side=[id])


class MinutesProfileVersion(Base):
    """Content is immutable once written; only status fields change."""

    __tablename__ = "minutes_profile_versions"
    __table_args__ = (UniqueConstraint("profile_id", "version_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("minutes_profiles.id"))
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[ProfileVersionStatus] = mapped_column(
        str_enum(ProfileVersionStatus), default=ProfileVersionStatus.PROPOSED
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSONType)
    content_schema_version: Mapped[int] = mapped_column(Integer)
    content_sha256: Mapped[str] = mapped_column(String(64))
    origin: Mapped[VersionOrigin] = mapped_column(str_enum(VersionOrigin))
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("minutes_profile_versions.id")
    )
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(String(255))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped[MinutesProfile] = relationship(back_populates="versions")
    parent: Mapped["MinutesProfileVersion | None"] = relationship(remote_side=[id])
