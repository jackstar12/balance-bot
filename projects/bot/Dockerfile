FROM base:latest

COPY lib /app/lib/
COPY projects/bot /app/projects/bot/

WORKDIR /app/projects/bot

RUN ~/.local/bin/poetry install --without dev


EXPOSE 5000

CMD [ "~/.local/bin/poetry", "run" ]
