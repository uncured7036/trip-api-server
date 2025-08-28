FROM python:3.10-slim

WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt

CMD ["sh", "-c", "uvicorn main:api --host 0.0.0.0 --port $PORT"]
