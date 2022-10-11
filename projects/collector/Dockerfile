FROM base:latest

COPY lib /app/lib/
COPY projects/collector /app/projects/collector/

WORKDIR /app/projects/collector

RUN ~/.local/bin/poetry install --without dev

EXPOSE 5000

CMD [ "python3", "__main__.py" ]