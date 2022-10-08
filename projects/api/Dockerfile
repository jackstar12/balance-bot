FROM base:latest

COPY lib /app/lib/
COPY projects/api /app/projects/api/

WORKDIR /app/projects/api

RUN ~/.local/bin/poetry install --without dev

EXPOSE 5000

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "5000"]