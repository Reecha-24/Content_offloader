"""HTTP wrapper around the LangGraph content pipeline.

Save your original script as backend/graph.py (same folder as this file).
Run:  uvicorn api:app --port 8000      (no --reload on Windows, see README)
"""
import asyncio
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from langgraph.types import Command

from main import content_graph

app = FastAPI(title="Content Offloader API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TASKS: dict[str, asyncio.Task] = {}
ERRORS: dict[str, str] = {}


class StartBody(BaseModel):
    topic: str = Field(..., min_length=2, max_length=500)


class ResumeBody(BaseModel):
    approved: bool
    feedback: Optional[str] = None


def cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


async def _run(thread_id: str, payload):
    ERRORS.pop(thread_id, None)
    try:
        await content_graph.ainvoke(payload, config=cfg(thread_id))
    except Exception as e:  # surfaced to the UI via GET /runs/{id}
        ERRORS[thread_id] = f"{type(e).__name__}: {e}"


@app.post("/runs")
async def start_run(body: StartBody):
    thread_id = str(uuid.uuid4())
    TASKS[thread_id] = asyncio.create_task(_run(thread_id, {"topic": body.topic.strip()}))
    return {"thread_id": thread_id, "status": "running"}


@app.get("/runs/{thread_id}")
async def get_run(thread_id: str):
    task = TASKS.get(thread_id)
    if task is None:
        raise HTTPException(404, "Unknown run")

    snap = await content_graph.aget_state(cfg(thread_id))
    values = snap.values or {}
    interrupt_payload = None

    if not task.done():
        status = "running"
    elif thread_id in ERRORS:
        status = "error"
    elif snap.next:
        status = "awaiting_approval"
        for t in snap.tasks:
            if t.interrupts:
                interrupt_payload = t.interrupts[0].value
                break
    elif values.get("initial_route") == "__end__":
        status = "blocked"
    else:
        status = "completed"

    return {
        "thread_id": thread_id,
        "status": status,
        "values": values,
        "interrupt": interrupt_payload,
        "error": ERRORS.get(thread_id),
    }


@app.post("/runs/{thread_id}/resume")
async def resume_run(thread_id: str, body: ResumeBody):
    task = TASKS.get(thread_id)
    if task is None:
        raise HTTPException(404, "Unknown run")
    if not task.done():
        raise HTTPException(409, "Run is still working")
    snap = await content_graph.aget_state(cfg(thread_id))
    if not snap.next:
        raise HTTPException(409, "Run is not waiting for approval")

    payload = Command(
        resume={"human_approved": body.approved, "human_feedback": body.feedback}
    )
    TASKS[thread_id] = asyncio.create_task(_run(thread_id, payload))
    return {"thread_id": thread_id, "status": "running"}
