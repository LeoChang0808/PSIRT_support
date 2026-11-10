FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN groupadd --system psirt && useradd --system --gid psirt psirt
COPY *.py ./
COPY templates/ ./templates/
COPY static/ ./static/
COPY form/ ./form/

USER psirt
EXPOSE 8765

CMD ["gunicorn", "--bind", "0.0.0.0:8765", "--workers", "2", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
