FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install --no-install-recommends -y \
        build-essential \
        curl \
        ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY alembic/ ./alembic/
COPY setrem_estagio_canis/ ./setrem_estagio_canis/

RUN pip install --no-cache-dir .

CMD ["uvicorn", "setrem_estagio_canis.main:app", "--host", "0.0.0.0", "--port", "8000"]
