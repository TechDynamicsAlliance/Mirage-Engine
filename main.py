"""MIRAGE API — FastAPI application.

Endpoints (per GUIDE Lesson 6):
  GET  /health              → server status
  GET  /api/dishes          → list available dishes + their goals
  POST /api/reformulate     → the core engine call
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal

from engine import reformulate, list_dishes, load_data, MirageError, DishNotFound

app = FastAPI(
    title="MIRAGE API",
    description="Reformulate recipes to reduce sodium/sugar/fat while preserving taste.",
    version="1.0.0",
)

# CORS — allow the Expo/React Native dev server (any origin during hackathon)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load data once at startup
DATA = load_data()


# ── Request / Response models ───────────────────────────────────────
class ReformulateRequest(BaseModel):
    dish: str = Field(..., description="Dish name, e.g. 'lemonade'")
    goal: Literal["sugar", "salt", "fat"] = Field(..., description="What to reduce")
    reduce_percent: int = Field(
        ..., ge=1, le=80,
        description="How much to reduce (1–80%)"
    )


# ── Endpoints ───────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "engine": "mirage", "version": "1.0.0"}


@app.get("/api/dishes")
async def get_dishes():
    """List available dishes and their applicable goals."""
    return list_dishes(DATA)


@app.post("/api/reformulate")
async def do_reformulate(req: ReformulateRequest):
    """Run the MIRAGE reformulation engine."""
    try:
        result = reformulate(
            dish=req.dish,
            goal=req.goal,
            reduce_percent=req.reduce_percent,
            data=DATA,
        )
        return result
    except DishNotFound as e:
        raise HTTPException(status_code=404, detail=str(e))
    except MirageError as e:
        raise HTTPException(status_code=422, detail=str(e))
