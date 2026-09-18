# Dashboard: one web page with buttons for the common steps. It serves the page
# and forwards a fixed list of requests to Docker 1, 4 and 5, so the browser only
# ever talks to this one address. Not one of the six stack services: nothing
# depends on it.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
RUN python -m pip install --upgrade pip setuptools wheel
COPY requirements/base.txt requirements/dashboard.txt /app/requirements/
RUN pip install --no-cache-dir -r /app/requirements/dashboard.txt
COPY src/dashboard_service /app/src/dashboard_service
# Reused by the "drone IDs from CrazySwarm" button, which reads crazyflies.yaml
# and rewrites config.yaml the same way ./scripts/swarm_config.py set does.
COPY scripts/swarm_config.py /app/tools/swarm_config.py
CMD ["uvicorn", "dashboard_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
