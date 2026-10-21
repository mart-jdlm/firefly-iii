FROM python:3.13-alpine

RUN apk add --no-cache tzdata

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY server.py /app/
USER nobody
CMD ["python", "/app/server.py"]
