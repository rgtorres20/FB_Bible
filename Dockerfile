# The "design for both" half: same app, long-running container.
# Phase 3 (cron jobs + database + web push) needs this shape, not serverless.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# pyproject.toml is the single source of dependency truth. The [server] extra
# adds uvicorn, which only a long-running process needs -- Vercel supplies its
# own ASGI server and does not install it.
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir ".[server]"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
