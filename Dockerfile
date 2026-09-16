# One image definition for every service in this stack.
#
# Each service differs only in its requirements file, its package directory and
# its start command, so they are build args instead of six near-identical files.
#
#   docker build --build-arg SERVICE=mission --target runtime .
#
# Targets:
#   runtime  every HTTP service (default command: uvicorn)
#   control  runtime + the vendored AirSim client (DRONE_MODE=airsim only)
#   desktop  the OpenCV visualizer, which needs X11 libraries and its own command
#
# SERVICE names the package without its "_service" suffix, e.g. SERVICE=mission
# uses requirements/mission.txt and the mission_service package.

ARG PYTHON_VERSION=3.11

FROM python:${PYTHON_VERSION}-slim AS base
ARG SERVICE
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    SERVICE=${SERVICE}
WORKDIR /app
RUN python -m pip install --upgrade pip setuptools wheel
COPY requirements /app/requirements
RUN pip install --no-cache-dir -r /app/requirements/${SERVICE}.txt
COPY drone_common /app/drone_common
COPY ${SERVICE}_service /app/${SERVICE}_service
# Shell form so ${SERVICE} and ${PORT} are expanded at start time.
CMD ["sh", "-c", "uvicorn ${SERVICE}_service.app:app --host 0.0.0.0 --port ${PORT:-8000}"]

FROM base AS runtime

FROM base AS control
# The legacy AirSim backend imports this vendored client at DRONE_MODE=airsim.
COPY airsim /app/airsim

FROM base AS desktop
# OpenCV needs these shared libraries to open a window on the host X server.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libxext6 libsm6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*
CMD ["sh", "-c", "python -m ${SERVICE}_service.viewer"]
