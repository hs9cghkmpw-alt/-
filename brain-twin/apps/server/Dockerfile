# Brain Twin server (FastAPI + SQLAlchemy + Alembic)
#
# ビルドコンテキストはリポジトリルート(docker-compose.ymlのcontext: .)。
# packages/ (prompts/rules/shared-types) を同梱し、PACKAGES_DIR=/packages で参照する。
FROM python:3.12-slim

WORKDIR /app

# curl: docker-compose.ymlのhealthcheckで使用。
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY apps/server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/server/ ./
COPY packages/ /packages/

ENV PACKAGES_DIR=/packages \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
