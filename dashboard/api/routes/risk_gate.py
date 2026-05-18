"""
Risk gate endpoints.

GET /api/risk-gate      -- list validation decisions with filtering
GET /api/risk-gate/{id} -- single validation record with full details
"""

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query

from db import get_db, is_specific_bot
from models import (
    Envelope,
    Meta,
    RiskGateDetail,
    RiskGateRecord,
)

router = APIRouter(prefix="/api/risk-gate", tags=["risk-gate"])


@router.get("", response_model=Envelope[list[RiskGateRecord]])
def get_risk_gate_decisions(
    bot: str = Query("both"),
    decision: Optional[str] = Query(None, description="Filter: PROCEED or VETO"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    if bot == "all":
        bot = "both"
    """Return risk gate decisions from the validations table.

    Maps validations fields to the dashboard model:
    - symbol = kalshi_ticker (the identifier column)
    - confluence = mirofish_prob * 5 (scaled to match 0-5 score)
    """
    clauses: list[str] = []
    params: list = []

    if is_specific_bot(bot):
        clauses.append("bot_id = %s")
        params.append(bot)
    if decision:
        clauses.append("decision = %s")
        params.append(decision.upper())

    where = ""
    if clauses:
        where = "WHERE " + " AND ".join(clauses)

    query = f"""
        SELECT id, timestamp, kalshi_ticker, event_title,
               mirofish_prob, decision, confidence,
               risk_assessment, veto_reason, proposed_side
        FROM validations
        {where}
        ORDER BY timestamp DESC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, offset])

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    data = []
    for r in rows:
        data.append(
            RiskGateRecord(
                id=r["id"],
                timestamp=r["timestamp"],
                symbol=r["kalshi_ticker"],
                event_title=r["event_title"],
                confluence=round((r["mirofish_prob"] or 0) * 5, 2),
                decision=r["decision"],
                confidence=r.get("confidence"),
                risk_assessment=r.get("risk_assessment"),
                veto_reason=r.get("veto_reason"),
                proposed_side=r.get("proposed_side"),
                mirofish_prob=r.get("mirofish_prob"),
            )
        )
    return Envelope(data=data, meta=Meta(count=len(data)))


@router.get("/{record_id}", response_model=Envelope[RiskGateDetail])
def get_risk_gate_detail(record_id: int):
    """Return a single validation record with all fields."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM validations WHERE id = %s", (record_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Validation record not found")

    detail = RiskGateDetail(
        id=row["id"],
        timestamp=row["timestamp"],
        symbol=row["kalshi_ticker"],
        event_title=row["event_title"],
        confluence=round((row["mirofish_prob"] or 0) * 5, 2),
        decision=row["decision"],
        confidence=row.get("confidence"),
        risk_assessment=row.get("risk_assessment"),
        veto_reason=row.get("veto_reason"),
        proposed_side=row.get("proposed_side"),
        mirofish_prob=row.get("mirofish_prob"),
        kalshi_price=row.get("kalshi_price"),
        gap=row.get("gap"),
        adjusted_probability=row.get("adjusted_probability"),
        size_multiplier=row.get("size_multiplier"),
        sentiment_report=row.get("sentiment_report"),
        news_report=row.get("news_report"),
        contrarian_report=row.get("contrarian_report"),
        trade_id=row.get("trade_id"),
    )
    return Envelope(data=detail, meta=Meta(count=1))
