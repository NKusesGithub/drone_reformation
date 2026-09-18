# Docker 1: drone-control gateway.
# The only service that talks to the CrazySwarm HTTP bridge. It runs on the
# host network, so it binds port 8001 on the host directly.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src:/app/third_party
RUN python -m pip install --upgrade pip setuptools wheel
COPY requirements/base.txt requirements/drone_control.txt /app/requirements/
RUN pip install --no-cache-dir -r /app/requirements/drone_control.txt
COPY src/drone_common /app/src/drone_common
# Only used by the legacy DRONE_MODE=airsim backend.
COPY third_party/airsim /app/third_party/airsim
COPY src/drone_control_service /app/src/drone_control_service
CMD ["uvicorn", "drone_control_service.app:app", "--host", "0.0.0.0", "--port", "8001"]
