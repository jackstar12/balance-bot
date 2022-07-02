FROM tradealpha_common:latest

WORKDIR /code

COPY /tradealpha/api/requirements.txt /code/tradealpha/api/requirements.txt

RUN pip install --no-cache-dir --upgrade -r ./tradealpha/api/requirements.txt

COPY /tradealpha/api /code/tradealpha/api

EXPOSE 5000

CMD ["uvicorn", "tradealpha.api.app:app", "--host", "0.0.0.0", "--port", "5000"]