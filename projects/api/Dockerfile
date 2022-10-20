FROM python:3.10.3

COPY lib /app/lib/
COPY projects/api /app/projects/api/

WORKDIR /app/projects/api

RUN curl -sSL https://install.python-poetry.org | python3 - &&\
    export PATH=$PATH:$HOME/.local/bin &&\
    poetry config virtualenvs.create false &&\
    RUN ~/.local/bin/poetry install --without dev

EXPOSE 5000

CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "5000"]