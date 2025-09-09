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
GLOBAL_USER_ID = 'GLOBAL_USER_ID'

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
    startTimeUtc: datetime
    duration: int  # in minutes
    endTimeUtc: datetime
    timeZone: str
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
    interests: Optional[list[str]] = None
    pace: Optional[str] = None
    transportType: Optional[list[Literal[
        "train", "highSpeedTrain", "flight", "bus", "taxi",
        "bike", "walk", "car", "boat", "motorcycle", "other"
    ]]] = None


class UpdatePayload(BaseModel):
    itinerary: Optional[AgentResponse] = None
    sessionId: Optional[str] = None
    text: str


class UpdateResponse(BaseModel):
    itinerary: Optional[AgentResponse] = None
    sessionId: str
    text: Optional[str] = None


class DeletePayload(BaseModel):
    sessionId: str


@api.post('/delete')
async def delete(payload: DeletePayload):
    try:
        await remote_agent.async_delete_session(user_id=GLOBAL_USER_ID, session_id=payload.sessionId)
    except Exception as e:
        logger.error(f'exception: {e}')
    return JSONResponse(status_code=200, content={'error': None})


@api.post('/update')
async def update(payload: UpdatePayload):
    text = ''
    try:
        if payload.sessionId:
            # validate session id
            session = await remote_agent.async_get_session(user_id=GLOBAL_USER_ID,
                                                           session_id=payload.sessionId)
        elif payload.itinerary:
            # create session
            session = await remote_agent.async_create_session(user_id=GLOBAL_USER_ID)
            text = f'Please help me to modify this itinerary:\n'
            text += payload.itinerary.model_dump_json() + f'\n'
        else:
            # fail
            raise Exception('Either sessionId or itinerary is missing')
    except Exception as e:
        # session fail
        return JSONResponse(
            status_code=400,
            content={"error": "Either sessionId or itinerary is missing"}
        )
    # chat with session id
    text += payload.text
    itinerary = ''
    full_text = ''
    async for event in remote_agent.async_stream_query(
        user_id=GLOBAL_USER_ID,
        session_id=session['id'],
        message=text,
    ):
        for resp in event['content']['parts']:
            if 'text' in resp:
                full_text += resp['text']

    if 'STARTJSON' in full_text and 'ENDJSON' in full_text:
        startjson = full_text.find('STARTJSON')
        endjson = full_text.find('ENDJSON')
        itinerary = full_text[startjson + 9:endjson]
        full_text = full_text[:startjson] + full_text[endjson + 7:]

    try:
        validated = AgentResponse.model_validate_json(itinerary)
        resp = UpdateResponse(
            itinerary=validated,
            sessionId=session['id'],
            text=full_text
        )
    except Exception:
        resp = UpdateResponse(
            sessionId=session['id'],
            text=full_text
        )

    return Response(content=resp.model_dump_json(), media_type='application/json')


@api.post('/query')
async def query(payload: QueryPayload):
    return await get(payload)


@api.post('/get')
async def get(payload: QueryPayload):
    prompt = (
        f'Please plan a {payload.days}-days trip starting from '
        f'{payload.startDate} in {", ".join(payload.locations)}. '
    )
    if payload.interests:
        prompt += f'The purposes of the trip are '
        prompt += ','.join(payload.interests) + '. '
    if payload.pace:
        prompt += f'The trip follows a {payload.pace} pace. '
    if payload.transportType:
        prompt += f'The prefered transport types for this trip are '
        prompt += ','.join(payload.transportType) + '. '
    prompt += (
        f'Please give a title of this trip. '
        f'Use {payload.language} for value of title, location, note, and name. '
        f'All remaining values should be in English. '
        f'No extra commentary or formatting. '
        f'Do not include any explanations, markdown, or extra text. '
        f'Output the JSON without additional explanation. '
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
                if 'STARTJSON' in full_text and 'ENDJSON' in full_text:
                    startjson = full_text.find('STARTJSON')
                    endjson = full_text.find('ENDJSON')
                    full_text = full_text[startjson + 9:endjson]
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

