FROM python:3.10.3

WORKDIR /code

COPY /tradealpha/common/requirements.txt /code/tradealpha/common/requirements.txt

RUN pip install --no-cache-dir --upgrade -r ./tradealpha/common/requirements.txt

COPY /tradealpha/common /code/tradealpha/common
COPY ./alembic.ini /code/alembic.ini
COPY ./alembic /code/alembic
COPY ./.env /code/.env

RUN echo "Trade Alpha"