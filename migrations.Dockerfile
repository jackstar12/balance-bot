FROM balancebot_common:latest

CMD ["alembic", "upgrade", "head"]