FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY pipeline/api_v6/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY pipeline/api_v6 pipeline/api_v6
COPY pipeline/dashboard-v6-postgres pipeline/dashboard-v6-postgres

RUN useradd --create-home --shell /usr/sbin/nologin cplan
USER cplan

EXPOSE 8780
CMD ["uvicorn", "pipeline.api_v6.app:create_environment_app", "--factory", "--host", "0.0.0.0", "--port", "8780"]
