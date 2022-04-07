FROM python:3.8

WORKDIR /code

COPY ./balancebot/bot/requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r requirements.txt

COPY ./balancebot/common ./code/common
COPY ./balancebot/bot ./code/bot

RUN [ "python3", "bot.py" ]