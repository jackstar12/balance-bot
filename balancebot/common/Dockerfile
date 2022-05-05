FROM python:3.8

WORKDIR /code

COPY ./balancebot/common/requirements.txt /code/balancebot/common/requirements.txt
RUN pip install --no-cache-dir --upgrade -r ./balancebot/common/requirements.txt
COPY ./balancebot/common /code/balancebot/common

ENV PYTHONPATH=./

CMD ["python3", "balancebot/collector/collector.py"]