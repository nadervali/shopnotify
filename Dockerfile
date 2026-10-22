FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml .
COPY shopnotify ./shopnotify
RUN pip install --no-cache-dir .

COPY examples ./examples

ENV LOG_DB=/app/data/deliveries.db
VOLUME ["/app/data"]

ENTRYPOINT ["shopnotify"]
CMD ["--help"]
