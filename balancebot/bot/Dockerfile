FROM balancebot_common:latest

WORKDIR /code

COPY /balancebot/bot/requirements.txt /code/balancebot/bot/requirements.txt

RUN pip install --no-cache-dir --upgrade -r ./balancebot/bot/requirements.txt

COPY /balancebot/bot /code/balancebot/bot

RUN alembic upgrade head

CMD [ "python3", "-m", "balancebot.bot.bot" ]