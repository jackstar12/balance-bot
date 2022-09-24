FROM tradealpha_common:latest

COPY ./init_db.py /code/init_db.py

CMD ["python3", "init_db.py"]
