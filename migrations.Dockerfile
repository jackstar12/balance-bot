FROM tradealpha_common:latest

CMD ["alembic", "upgrade", "head"]
