import uvicorn

from api.app import app
from os import environ


def run():
    uvicorn.run(app, host='localhost', port=environ.get('PORT', 5000), workers=4)


if __name__ == '__main__':
    run()
