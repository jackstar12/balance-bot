FROM tradealpha_common:latest

WORKDIR /code

COPY /tradealpha/bot/requirements.txt /code/tradealpha/bot/requirements.txt

RUN pip install --no-cache-dir --upgrade -r ./tradealpha/bot/requirements.txt

COPY /tradealpha/bot /code/tradealpha/bot

CMD [ "python3", "-m", "tradealpha.bot.bot" ]