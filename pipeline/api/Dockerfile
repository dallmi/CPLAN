FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY pipeline/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY pipeline/api pipeline/api
COPY pipeline/studio pipeline/studio

RUN useradd --create-home --shell /usr/sbin/nologin cplan
USER cplan

EXPOSE 8780
CMD ["uvicorn", "pipeline.api.app:create_environment_app", "--factory", "--host", "0.0.0.0", "--port", "8780"]
