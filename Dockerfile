FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 TM_DB=/data/tenders.db
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY migrations ./migrations
COPY config.yaml .
VOLUME /data
CMD ["python", "-m", "app.main", "serve"]
