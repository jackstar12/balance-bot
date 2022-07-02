docker build --tag tradealpha_common --file tradealpha/common/Dockerfile .
docker-compose build migrate
docker-compose up migrate