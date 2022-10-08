FROM python:3.10.3

COPY lib /app/lib/
COPY projects/bot /app/projects/bot/

WORKDIR /app/projects/bot

RUN curl -sSL https://install.python-poetry.org | python3 -
RUN ~/.local/bin/poetry config virtualenvs.create false
RUN ~/.local/bin/poetry install --without dev


EXPOSE 5000

CMD [ "~/.local/bin/poetry", "run" ]
