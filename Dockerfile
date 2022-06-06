FROM python:3.10.3

WORKDIR /code

COPY ./balancebot/api/requirements.txt /code/balancebot/api/requirements.txt
COPY ./balancebot/common/requirements.txt /code/balancebot/common/requirements.txt

RUN pip install --no-cache-dir --upgrade -r ./balancebot/api/requirements.txt
RUN pip install --no-cache-dir --upgrade -r ./balancebot/common/requirements.txt

COPY ./balancebot/api /code/balancebot/api
COPY ./balancebot/common /code/balancebot/common


CMD ["uvicorn", "balancebot.api.app:app", "--port", "5000"]