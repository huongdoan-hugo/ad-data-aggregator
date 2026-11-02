FROM python:3.13-slim

WORKDIR /app
COPY aggregator.py .

ENTRYPOINT ["python", "aggregator.py"]
CMD ["--input", "/data/ad_data.csv", "--output", "/results"]
