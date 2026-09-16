# Docker 4: mission orchestrator. The only service that issues commands; it
# reaches Docker 1 over HTTP and never imports ROS 2 or CrazySwarm libraries.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
RUN python -m pip install --upgrade pip setuptools wheel
COPY requirements/base.txt requirements/mission.txt /app/requirements/
RUN pip install --no-cache-dir -r /app/requirements/mission.txt
COPY drone_common /app/drone_common
COPY mission_service /app/mission_service
CMD ["uvicorn", "mission_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
