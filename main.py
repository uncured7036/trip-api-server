import os
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from vertexai import agent_engines
import vertexai
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
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
    transportType: Optional[Literal[
        "train", "highSpeedTrain", "flight", "bus", "taxi",
        "bike", "walk", "car", "boat", "motorcycle", "other"
    ]] = None
    note: str
    childActivities: List[ChildActivity] = Field(default_factory=list)


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
    async for event in remote_agent.async_stream_query(
        user_id="USER_ID",
        message=prompt,
    ):
        for resp in event['content']['parts']:
            if 'text' in resp:
                full_text = resp['text']
                # trim markdown format
                first_brace = full_text.index('{')
                if first_brace > 0:
                    full_text = full_text[first_brace:-3]
                break

    try:
        validated = AgentResponse.model_validate_json(full_text)
        return JSONResponse(content=validated.model_dump_json())
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": "Failed to parse or validate agent response",
                     "details": str(e),
                    },
        )

