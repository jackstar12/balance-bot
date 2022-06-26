docker build --tag balancebot_common --file balancebot/common/Dockerfile .
docker-compose build && docker-compose up migrate
docker-compose up