FROM python:3.10.3

WORKDIR /code

COPY ./balancebot/bot/requirements.txt /code/balancebot/bot/requirements.txt
COPY ./balancebot/common/requirements.txt /code/balancebot/common/requirements.txt

RUN pip install --no-cache-dir --upgrade -r ./balancebot/bot/requirements.txt
RUN pip install --no-cache-dir --upgrade -r ./balancebot/common/requirements.txt

COPY ./balancebot/common ./code/common
COPY ./balancebot/bot ./code/bot

CMD [ "python3", "-m", "balancebot.bot.bot" ]