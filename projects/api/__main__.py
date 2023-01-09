import uvicorn
from os import environ

from api.app import app


def run():
    uvicorn.run(app, host='0.0.0.0', port=5000)


if __name__ == '__main__':
    run()
