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
# --no-proxy-headers: there is no reverse proxy in this image, and uvicorn's
# default would let a caller rewrite its own source address with an
# X-Forwarded-For header -- the address the login rate limit counts against
# (pipeline/api/login_guard.py).
CMD ["uvicorn", "pipeline.api.app:create_environment_app", "--factory", "--no-proxy-headers", "--host", "0.0.0.0", "--port", "8780"]
