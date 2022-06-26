FROM python:3.10.3

WORKDIR /code

COPY /balancebot/common/requirements.txt /code/balancebot/common/requirements.txt

RUN pip install --no-cache-dir --upgrade -r ./balancebot/common/requirements.txt

COPY /balancebot/common /code/balancebot/common
COPY ./alembic.ini /code/alembic.ini
COPY ./alembic /code/alembic

RUN echo "Trade Alpha"