FROM python:3.10.3-bullseye

RUN curl -sSL https://install.python-poetry.org | python3 - &&\
    export PATH=$PATH:$HOME/.local/bin &&\
    poetry config virtualenvs.create false

CMD ["echo", "hi!"]