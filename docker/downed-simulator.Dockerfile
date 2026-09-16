# Docker 5: downed-drone simulator (fault injection). It calls Docker 4, which
# calls Docker 1, so a simulated loss follows the same path as a real one.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app
RUN python -m pip install --upgrade pip setuptools wheel
COPY requirements/base.txt requirements/downed_simulator.txt /app/requirements/
RUN pip install --no-cache-dir -r /app/requirements/downed_simulator.txt
COPY drone_common /app/drone_common
COPY downed_simulator_service /app/downed_simulator_service
CMD ["uvicorn", "downed_simulator_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
