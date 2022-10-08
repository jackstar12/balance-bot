FROM python:3.10.3

RUN curl -sSL https://install.python-poetry.org | python3 -
RUN ~/.local/bin/poetry config virtualenvs.create false

CMD ["echo", "hi!"]