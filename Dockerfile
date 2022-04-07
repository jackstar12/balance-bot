FROM python:3.8

WORKDIR /code

COPY ./requirements.txt /code/requirements.txt

RUN pip install --no-cache-dir --upgrade -r requirements.txt
RUN pip install --no-cache-dir --upgrade uvicorn[standard]
RUN pip install --no-cache-dir --upgrade fastapi_jwt_auth

COPY ./balancebot /code/balancebot

ENV PORT = 5000
EXPOSE 5000

CMD [ "uvicorn" , "balancebot.api.app:app", "--port", "5000"]
