FROM python:3.11-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY static static
COPY config config
COPY data/processed data/processed
COPY data/sample data/sample
COPY ml/artifacts/*.json ml/artifacts/
ENV JALSETU_DB=/data/jalsetu.db
RUN mkdir -p /data
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
