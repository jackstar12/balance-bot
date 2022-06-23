FROM balancebot_common:latest

WORKDIR /code

COPY /balancebot/api/requirements.txt /code/balancebot/api/requirements.txt

RUN pip install --no-cache-dir --upgrade -r ./balancebot/api/requirements.txt

COPY /balancebot/api /code/balancebot/api

EXPOSE 5000

CMD ["alembic", "upgrade", "head"]
CMD ["uvicorn", "balancebot.api.app:app", "--host", "0.0.0.0", "--port", "5000"]