FROM python:3.8

WORKDIR /code

COPY ./balancebot/collector/requirements.txt /code/balancebot/collector/requirements.txt
COPY ./balancebot/common/requirements.txt /code/balancebot/common/requirements.txt

RUN pip install --no-cache-dir --upgrade -r ./balancebot/collector/requirements.txt
RUN pip install --no-cache-dir --upgrade -r ./balancebot/common/requirements.txt

COPY ./balancebot/collector /code/balancebot/collector
COPY ./balancebot/common /code/balancebot/common

COPY .env /code/.env

CMD ["python3", "-m", "balancebot.collector.collector"]