docker build --tag balancebot_common --file balancebot/common/Dockerfile .
docker-compose build migrate
docker-compose up migrate