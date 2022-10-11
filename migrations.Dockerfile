FROM base:latest

COPY lib /app/lib/

WORKDIR /app/lib/database

RUN ~/.local/bin/poetry install --without dev

CMD ["alembic", "upgrade", "head"]