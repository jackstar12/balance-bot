FROM balancebot_common:latest

WORKDIR /code

COPY /balancebot/collector/requirements.txt /code/balancebot/collector/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/balancebot/collector/requirements.txt

COPY /balancebot/collector /code/balancebot/collector

CMD ["alembic", "upgrade", "head"]

CMD ["python3", "-m", "balancebot.collector.collector"]
