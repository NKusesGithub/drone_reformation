# Docker 3: formation generator. Pure geometry: it returns slot offsets and
# knows nothing about which drones exist. Swap the shape logic by editing
# src/formation_service/.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
RUN python -m pip install --upgrade pip setuptools wheel
COPY requirements/base.txt requirements/formation.txt /app/requirements/
RUN pip install --no-cache-dir -r /app/requirements/formation.txt
COPY src/formation_service /app/src/formation_service
CMD ["uvicorn", "formation_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
