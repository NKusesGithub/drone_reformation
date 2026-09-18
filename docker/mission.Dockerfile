# Docker 4: mission orchestrator. The only service that issues commands; it
# reaches Docker 1 over HTTP and never imports ROS 2 or CrazySwarm libraries.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
RUN python -m pip install --upgrade pip setuptools wheel
COPY requirements/base.txt requirements/mission.txt /app/requirements/
RUN pip install --no-cache-dir -r /app/requirements/mission.txt
COPY src/drone_common /app/src/drone_common
COPY src/mission_service /app/src/mission_service
CMD ["uvicorn", "mission_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
