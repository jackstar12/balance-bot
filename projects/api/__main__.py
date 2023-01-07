import uvicorn
from os import environ


def run():
    uvicorn.run('api.app:app', host='localhost', port=int(environ.get('PORT', '4000')), workers=4)


if __name__ == '__main__':
    run()
