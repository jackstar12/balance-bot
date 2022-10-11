FROM base:latest

COPY lib /app/lib/
COPY projects/bot /app/projects/bot/

WORKDIR /app/projects/bot

RUN ~/.local/bin/poetry install --without dev


CMD [ "python3", "__main__.py" ]
