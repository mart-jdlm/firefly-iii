FROM python:3.13-alpine

RUN apk add --no-cache tzdata

COPY app.py index.html /app/
COPY static /app/static
USER nobody
CMD ["python", "/app/app.py"]
