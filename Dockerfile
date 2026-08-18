FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY strata ./strata
COPY seeds ./seeds
RUN pip install --no-cache-dir .

ENV STRATA_DATA_DIR=/data
EXPOSE 8020
CMD ["python", "-m", "strata.app"]
