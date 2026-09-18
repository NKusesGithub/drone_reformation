# Docker 2: Hungarian assignment. A pure function over JSON: no state, and it
# never calls another service. Swap the solver by editing src/hungarian_service/.
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/src
RUN python -m pip install --upgrade pip setuptools wheel
COPY requirements/base.txt requirements/hungarian.txt /app/requirements/
RUN pip install --no-cache-dir -r /app/requirements/hungarian.txt
COPY src/hungarian_service /app/src/hungarian_service
CMD ["uvicorn", "hungarian_service.app:app", "--host", "0.0.0.0", "--port", "8000"]
