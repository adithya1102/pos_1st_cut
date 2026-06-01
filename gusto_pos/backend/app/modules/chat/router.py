import traceback
import uuid
from datetime import datetime

import faiss
import numpy as np
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.order_items.model import OrderItem
from app.modules.orders.model import Order
from app.modules.outlets.model import Table

router = APIRouter(prefix="/chat", tags=["Gusto AI"])

# ---------------------------------------------------------------------------
# NLP model — loaded once at startup, stays in RAM for every request
# ---------------------------------------------------------------------------
_model = SentenceTransformer("all-MiniLM-L6-v2")

# ---------------------------------------------------------------------------
# Intent corpus — natural-language training phrases per intent
# ---------------------------------------------------------------------------
_INTENT_CORPUS: dict[str, list[str]] = {
    "total_revenue": [
        "What is the total revenue today?",
        "How much money did we make today?",
        "Show me today's sales",
        "Total earnings so far",
        "What are today's total sales?",
        "How much have we earned today?",
        "Give me today's revenue",
        "Revenue for today",
        "What did we earn today?",
        "How much did we make?",
        "Today's income",
        "Total sales amount",
        "Today's total revenue",
    ],
    "dish_sales_count": [
        "How many dishes did we sell today?",
        "Total items sold today",
        "How many orders did we take?",
        "How many items were ordered today?",
        "Dishes sold today",
        "Number of items sold",
        "How many total items sold?",
        "Quantity of food sold today",
        "Total dish count",
        "How many food items ordered?",
        "Which dishes sold the most?",
        "Show me all dish sales",
    ],
    "free_tables": [
        "Show free tables",
        "How many tables are available?",
        "Are there any empty tables?",
        "Free tables",
        "Which tables are free?",
        "Available tables right now",
        "Tables not occupied",
        "How many tables are open?",
        "How many free tables right now?",
    ],
    "total_tables": [
        "Total table count",
        "How many tables do we have in total?",
        "Total tables",
        "What is the total number of tables?",
        "How many tables are there?",
        "Count all tables",
        "What is our total table capacity?",
        "Total seating capacity",
    ],
    "top_dish": [
        "What is our top dish?",
        "Best selling item",
        "Most popular dish today",
        "Top dish today",
        "What dish sold the most?",
        "Best dish today",
        "Most ordered item today",
        "Which item is selling the most?",
        "What is our top selling dish?",
    ],
    "pending_orders": [
        "How many orders are pending?",
        "Pending orders count",
        "How many orders are waiting?",
        "Orders not yet completed",
        "Active pending orders",
        "How many orders in the queue?",
        "Outstanding orders today",
        "Orders still open",
    ],
    "least_profit_margin": [
        "Which item has the lowest margin?",
        "Least profitable item",
        "Which dish has the lowest profit margin?",
        "What is our least profitable item?",
        "Low margin dishes",
        "Which item makes us the least money?",
        "Least profit margin item",
        "What has the worst margin?",
        "Lowest margin dish",
    ],
    "customer_churn": [
        "What is the churn risk for my customers?",
        "Customer churn analysis",
        "How many customers are at risk of leaving?",
        "Churn rate for customers",
        "Which customers are churning?",
        "Customer retention risk",
        "Customer loyalty risk",
        "Are we losing customers?",
        "Customer churn rate",
    ],
}

# Build flat lists: phrase index → intent name
_phrases: list[str] = []
_phrase_intents: list[str] = []
for _intent, _plist in _INTENT_CORPUS.items():
    for _p in _plist:
        _phrases.append(_p)
        _phrase_intents.append(_intent)

# Encode corpus once; normalise so inner-product == cosine similarity
_corpus_vecs = _model.encode(
    _phrases, convert_to_numpy=True, normalize_embeddings=True
).astype(np.float32)

_index = faiss.IndexFlatIP(_corpus_vecs.shape[1])  # 384-dim for all-MiniLM-L6-v2
_index.add(_corpus_vecs)

CONFIDENCE_THRESHOLD = 0.65


def _today_start() -> datetime:
    return datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    query: str
    outlet_id: uuid.UUID


class AskResponse(BaseModel):
    answer: str
    intent: str | None = None
    confidence: float | None = None
    suggestions: list[str] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/ask", response_model=AskResponse)
async def ask_gusto(
    payload: AskRequest,
    db: AsyncSession = Depends(get_db),
):
    """Semantic intent router: FAISS cosine search maps the user query to an intent, then executes the matched SQL."""
    query_vec = _model.encode(
        [payload.query], convert_to_numpy=True, normalize_embeddings=True
    ).astype(np.float32)

    scores, indices = _index.search(query_vec, k=1)
    top_score = float(scores[0][0])
    top_idx = int(indices[0][0])

    if top_score < CONFIDENCE_THRESHOLD:
        return AskResponse(
            answer="I'm not sure I understand. Here are some things you can ask me:",
            intent=None,
            confidence=round(top_score, 4),
            suggestions=[
                "Today's total revenue",
                "Which dishes sold the most?",
                "How many free tables right now?",
                "What is our total table capacity?",
                "What is our top selling dish?",
                "Which item has the lowest margin?",
                "What is the churn risk for my customers?",
                "How many orders are pending?",
            ],
        )

    intent = _phrase_intents[top_idx]
    outlet_id = payload.outlet_id

    try:
        if intent == "total_revenue":
            result = await db.execute(
                select(func.coalesce(func.sum(Order.total_amount), 0))
                .where(
                    Order.outlet_id == outlet_id,
                    Order.created_at >= _today_start(),
                    Order.order_status != "cancelled",
                )
            )
            revenue = float(result.scalar_one())
            answer = f"Today's total revenue is ₹{revenue:,.2f}."

        elif intent == "dish_sales_count":
            result = await db.execute(
                select(OrderItem.name_snap, func.sum(OrderItem.quantity).label("qty"))
                .join(Order, OrderItem.order_id == Order.id)
                .where(
                    Order.outlet_id == outlet_id,
                    Order.created_at >= _today_start(),
                    Order.order_status != "cancelled",
                )
                .group_by(OrderItem.name_snap)
                .order_by(func.sum(OrderItem.quantity).desc())
            )
            rows = result.all()
            if not rows:
                answer = "No items have been sold today yet."
            else:
                parts = [f"{int(row.qty)}x {row.name_snap}" for row in rows]
                answer = "Today we sold: " + ", ".join(parts) + "."

        elif intent == "free_tables":
            # schema.sql defines tables.status as INTEGER DEFAULT 0 (0 = available)
            result = await db.execute(
                select(func.count(Table.id))
                .where(
                    Table.outlet_id == outlet_id,
                    Table.status == 0,
                )
            )
            count = result.scalar_one()
            answer = f"We currently have {count} free tables."

        elif intent == "total_tables":
            result = await db.execute(
                select(func.count(Table.id))
                .where(Table.outlet_id == outlet_id)
            )
            count = result.scalar_one()
            answer = f"We have a total of {count} tables."

        elif intent == "top_dish":
            result = await db.execute(
                select(OrderItem.name_snap, func.sum(OrderItem.quantity).label("total_qty"))
                .join(Order, OrderItem.order_id == Order.id)
                .where(
                    Order.outlet_id == outlet_id,
                    Order.created_at >= _today_start(),
                    Order.order_status != "cancelled",
                )
                .group_by(OrderItem.name_snap)
                .order_by(func.sum(OrderItem.quantity).desc())
                .limit(1)
            )
            row = result.first()
            if row is None:
                answer = "No dishes have been sold today yet."
            else:
                answer = f"Our top dish today is {row.name_snap} with {int(row.total_qty)} orders."

        elif intent == "pending_orders":
            result = await db.execute(
                select(func.count(Order.id))
                .where(
                    Order.outlet_id == outlet_id,
                    Order.order_status == "pending",
                )
            )
            count = result.scalar_one()
            answer = f"There are currently {count} pending orders waiting to be processed."

        elif intent == "least_profit_margin":
            answer = (
                "I see you're asking about profit margins. "
                "I'm currently calculating that data from your latest inventory logs, "
                "but this feature isn't fully connected yet."
            )

        elif intent == "customer_churn":
            answer = (
                "I see you're asking about customer churn risk. "
                "I'm currently calculating that data from your customer history, "
                "but this feature isn't fully connected yet."
            )

        else:
            answer = "Intent recognised but no data tool is wired for it yet."

    except Exception as exc:
        traceback.print_exc()
        return AskResponse(
            answer=f"Sorry, I encountered an error fetching that data. Please try again.",
            intent=intent,
            confidence=round(top_score, 4),
        )

    return AskResponse(answer=answer, intent=intent, confidence=round(top_score, 4))


@router.get("/health")
async def chat_health():
    """Confirms the NLP model and FAISS index are ready."""
    return {
        "status": "ok",
        "model": "all-MiniLM-L6-v2",
        "index_size": _index.ntotal,
    }
