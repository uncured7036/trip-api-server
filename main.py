import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from vertexai import agent_engines
import vertexai
from pydantic import BaseModel, Field
from typing import List, Literal
from datetime import datetime
import json
from fastapi.responses import JSONResponse


api = FastAPI()

PROJECT_ID = os.environ.get('PROJECT_ID')
LOCATION = os.environ.get('LOCATION')
AGENT_ID = os.environ.get('AGENT_ID')

print(f'PROJECT_ID: {PROJECT_ID}')
print(f'LOCATION: {LOCATION}')
print(f'AGENT_ID: {AGENT_ID}')

vertexai.init(
    project=PROJECT_ID,
    location=LOCATION,
)


class ChildActivity(BaseModel):
    name: str
    duration: int  # in minutes


class Activity(BaseModel):
    type: Literal[
        "sightseeing", "restaurant", "shopping", "accommodation",
        "freeTime", "transport", "other"
    ]
    location: str
    startTime: datetime
    duration: int  # in minutes
    endTime: datetime
    transportType: Literal[
        "train", "highSpeedTrain", "flight", "bus", "taxi",
        "bike", "walk", "car", "boat", "motorcycle", "other"
    ]
    note: str
    childActivities: List[ChildActivity]


class AgentResponse(BaseModel):
    activities: List[Activity]


class QueryPayload(BaseModel):
    locations: list[str] = Field(..., example=["Tokyo"])
    startDate: str = Field(..., example="2025-09-10")
    days: int = Field(..., example=2)
    language: str = Field(..., example="Chinese Traditional")



@api.post("/query")
async def query(payload: QueryPayload):
    prompt = (
        f'Please plan a {payload.days}-days trip starting from '
        f'{payload.startDate} in {", ".join(payload.locations)}. '
        f'Use {payload.language} for all value data.'
    )

    remote_agent = agent_engines.get(AGENT_ID)

    full_text = ""
    async for chunk in remote_agent.async_stream_query(prompt):
        full_text += chunk["text"]

    try:
        parsed = json.loads(full_text)
        validated = AgentResponse(**parsed)
        return JSONResponse(content=validated.dict())
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": "Failed to parse or validate agent response", "details": str(e)}
        )

