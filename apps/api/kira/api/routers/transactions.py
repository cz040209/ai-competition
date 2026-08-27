"""The ledger: what is waiting, what is settled, and the ways to settle it."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from kira.api.deps import CurrentUser, SessionDep
from kira.api.schemas import ActivityResponse, CreateTransactionRequest, TransactionResponse
from kira.services.transactions import (
    Activity,
    AlreadySettled,
    InvalidTransaction,
    NotConfirmed,
    TransactionNotFound,
    TransactionView,
    confirm_draft,
    create_transaction,
    discard_draft,
    list_activity,
    unconfirm,
)

router = APIRouter(prefix="/v1/transactions", tags=["transactions"])

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such transaction")
SETTLED = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="That transaction has already been settled"
)
NOT_CONFIRMED = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="That transaction is not on the ledger"
)


@router.get("", response_model=ActivityResponse)
async def get_activity(
    user: CurrentUser,
    session: SessionDep,
    category: Annotated[str | None, Query(max_length=40)] = None,
) -> Activity:
    """The ledger, optionally narrowed to one category. Drafts and chips are never narrowed."""
    return await list_activity(session, user, category)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TransactionResponse)
async def post_transaction(
    body: CreateTransactionRequest, user: CurrentUser, session: SessionDep
) -> TransactionView:
    """Add spending. It lands as a draft whatever route it came in by."""
    try:
        view = await create_transaction(
            session,
            user,
            merchant=body.merchant,
            amount_sen=body.amount_sen,
            occurred_on=body.occurred_on,
            category=body.category,
            source=body.source,
            confidence=body.confidence,
            note=body.note,
        )
    except InvalidTransaction as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    await session.commit()
    return view


@router.post("/{transaction_id}/confirm", response_model=TransactionResponse)
async def post_confirm(
    transaction_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> TransactionView:
    try:
        view = await confirm_draft(session, user, transaction_id)
    except TransactionNotFound as exc:
        raise NOT_FOUND from exc
    except AlreadySettled as exc:
        raise SETTLED from exc
    await session.commit()
    return view


@router.post("/{transaction_id}/discard", response_model=TransactionResponse)
async def post_discard(
    transaction_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> TransactionView:
    try:
        view = await discard_draft(session, user, transaction_id)
    except TransactionNotFound as exc:
        raise NOT_FOUND from exc
    except AlreadySettled as exc:
        raise SETTLED from exc
    await session.commit()
    return view


@router.post("/{transaction_id}/unconfirm", response_model=TransactionResponse)
async def post_unconfirm(
    transaction_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> TransactionView:
    try:
        view = await unconfirm(session, user, transaction_id)
    except TransactionNotFound as exc:
        raise NOT_FOUND from exc
    except NotConfirmed as exc:
        raise NOT_CONFIRMED from exc
    await session.commit()
    return view
