from typing import Optional, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, insert, update
from app.crud.base import CrudBase
from app.models.ride import Ride
from app.models.ride_status_history import RideStatusHistory
from app.schemas.ride import RideSchema, RideCreate, RideUpdate, RideStatusChangeRequest


STATUSES = {
    "requested",
    "driver_assigned",
    "accepted",
    "arrived",
    "started",
    "completed",
    "canceled",
}

ALLOWED_TRANSITIONS = {
    "client": {
        "requested": {"canceled"},
        "driver_assigned": {"canceled"},
        "accepted": {"canceled"},
    },
    "driver": {
        "driver_assigned": {"accepted", "canceled"},
        "accepted": {"arrived", "canceled"},
        "arrived": {"started", "canceled"},
        "started": {"completed", "canceled"},
    },
    "system": {
        "requested": {"driver_assigned", "canceled"},
        "driver_assigned": {"accepted", "canceled"},
        "accepted": {"arrived", "canceled"},
        "arrived": {"started", "canceled"},
        "started": {"completed", "canceled"},
    },
}


class RideCrud(CrudBase[Ride, RideSchema]):
    def __init__(self) -> None:
        super().__init__(Ride, RideSchema)

    async def create(self, session: AsyncSession, create_obj: RideCreate) -> RideSchema | None:
        values = create_obj.model_dump()
        values.setdefault("status", "requested")
        stmt = insert(Ride).values(values).returning(Ride)
        res = await session.execute(stmt)
        ride = res.scalar_one_or_none()
        if not ride:
            return None
        hist = insert(RideStatusHistory).values(
            ride_id=ride.id,
            from_status=None,
            to_status="requested",
            changed_by=create_obj.client_id,
            actor_role="client",
            reason=None,
            meta=None,
            created_at=datetime.utcnow(),
        )
        await session.execute(hist)
        return RideSchema.model_validate(ride)

    async def update(self, session: AsyncSession, id: int, update_obj: RideUpdate) -> RideSchema | None:
        stmt = update(Ride).where(Ride.id == id).values(update_obj.model_dump(exclude_none=True)).returning(Ride)
        res = await session.execute(stmt)
        ride = res.scalar_one_or_none()
        return RideSchema.model_validate(ride) if ride else None

    async def change_status(
        self,
        session: AsyncSession,
        ride_id: int,
        req: RideStatusChangeRequest,
    ) -> RideSchema | None:
        res = await session.execute(select(Ride).where(Ride.id == ride_id))
        ride: Optional[Ride] = res.scalar_one_or_none()
        if not ride:
            return None
        current = ride.status or "requested"
        to_status = req.to_status
        role = req.actor_role
        if to_status not in STATUSES:
            raise ValueError("invalid status")
        allowed = ALLOWED_TRANSITIONS.get(role, {}).get(current, set())
        if to_status not in allowed:
            raise PermissionError("transition not allowed")
        updates: dict[str, Any] = {"status": to_status, "status_reason": req.reason}
        now = datetime.utcnow()
        if to_status == "started":
            updates["started_at"] = now
        if to_status == "completed":
            updates["completed_at"] = now
        if to_status == "canceled":
            updates["canceled_at"] = now
            updates["cancellation_reason"] = req.reason
        upd_stmt = update(Ride).where(Ride.id == ride_id).values(updates).returning(Ride)
        upd_res = await session.execute(upd_stmt)
        new_ride = upd_res.scalar_one_or_none()
        hist_stmt = insert(RideStatusHistory).values(
            ride_id=ride_id,
            from_status=current,
            to_status=to_status,
            changed_by=req.actor_id,
            actor_role=role,
            reason=req.reason,
            meta=req.meta,
            created_at=now,
        )
        await session.execute(hist_stmt)
        return RideSchema.model_validate(new_ride) if new_ride else None


ride_crud = RideCrud()
