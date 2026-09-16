# Docker 6: OpenCV visualizer. Not an HTTP service: it polls Docker 1 and
# opens a window on the host X server, so it needs the X11 shared libraries.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libxext6 libsm6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --upgrade pip setuptools wheel
COPY requirements/visualizer.txt /app/requirements/
RUN pip install --no-cache-dir -r /app/requirements/visualizer.txt
COPY visualizer_service /app/visualizer_service
CMD ["python", "-m", "visualizer_service.viewer"]
