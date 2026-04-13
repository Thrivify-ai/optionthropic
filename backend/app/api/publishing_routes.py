from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.broadcast_desk import (
    generate_broadcast_batch,
    get_broadcast_workspace,
    update_broadcast_draft_status,
)
from app.api.auth_routes import get_current_user
from app.db.database import get_db
from app.models.user import User

router = APIRouter(prefix="/publishing", tags=["publishing"])


class BroadcastStatusUpdate(BaseModel):
    status: str


@router.get("/workspace")
async def publishing_workspace(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    channel: str = "whatsapp",
) -> Any:
    return await get_broadcast_workspace(
        session,
        channel_type=channel,
        auto_generate=True,
        created_by_user_id=current_user.id,
    )


@router.post("/workspace/refresh")
async def refresh_publishing_workspace(
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    channel: str = "whatsapp",
) -> Any:
    await generate_broadcast_batch(
        session,
        channel_type=channel,
        created_by_user_id=current_user.id,
    )
    return await get_broadcast_workspace(
        session,
        channel_type=channel,
        auto_generate=False,
    )


@router.post("/drafts/{draft_id}/status")
async def set_broadcast_draft_status(
    draft_id: str,
    body: BroadcastStatusUpdate,
    session: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Any:
    try:
        draft = await update_broadcast_draft_status(
            session,
            draft_id=draft_id,
            status=body.status,
            current_user_id=current_user.id,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message)
        raise HTTPException(status_code=400, detail=message)

    return {"draft": draft}
