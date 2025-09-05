import os
import uuid
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
from vertexai import agent_engines
import vertexai
from pydantic import BaseModel, Field
from typing import List, Literal, Optional
from datetime import datetime
import json
from fastapi.responses import JSONResponse
import logging

logger = logging.getLogger('uvicorn.error')

api = FastAPI()

PROJECT_ID = os.environ.get('PROJECT_ID')
LOCATION = os.environ.get('LOCATION')
AGENT_ID = os.environ.get('AGENT_ID')

vertexai.init(
    project=PROJECT_ID,
    location=LOCATION,
)

remote_agent = agent_engines.get(AGENT_ID)

class ChildActivity(BaseModel):
    name: str
    duration: int  # in minutes


class LatLng(BaseModel):
    latitude: float
    longitude: float


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
    latLng: Optional[LatLng] = None
    placeUri: Optional[str] = None



class AgentResponse(BaseModel):
    title: str
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
        f'Please give a title of this trip. '
        f'Use {payload.language} for value of title, location, note, and name. '
        f'All remaining values should be in English.'
    )

    uid = str(uuid.uuid4())
    session = await remote_agent.async_create_session(user_id=uid)

    full_text = ""
    async for event in remote_agent.async_stream_query(
        user_id=uid,
        session_id=session['id'],
        message=prompt,
    ):
        for resp in event['content']['parts']:
            if 'text' in resp:
                full_text = resp['text']
                # trim markdown format
                first_brace = full_text.find('{')
                if first_brace > 0:
                    full_text = full_text[first_brace:-3]
                break

    await remote_agent.async_delete_session(user_id=uid, session_id=session['id'])

    try:
        validated = AgentResponse.model_validate_json(full_text)
        return Response(content=validated.model_dump_json(), media_type='application/json')
    except Exception as e:
        logger.error(f'exception: {e}\n full_text: {full_text}')
        return JSONResponse(
            status_code=400,
            content={"error": "Failed to parse or validate agent response",
                     "details": str(e),
                    },
        )

