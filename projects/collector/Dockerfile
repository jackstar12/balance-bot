FROM tradealpha_common:latest

WORKDIR /code

COPY /tradealpha/collector/requirements.txt /code/tradealpha/collector/requirements.txt

RUN pip install --no-cache-dir --upgrade -r /code/projects/collector/requirements.txt

COPY /tradealpha/collector /code/tradealpha/collector

CMD ["alembic", "upgrade", "head"]

CMD ["python3", "-m", "tradealpha.collector.collector"]
