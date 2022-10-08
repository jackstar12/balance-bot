import uvicorn

from api.app import app

def run():
    uvicorn.run(app, host='localhost', port=5000)


if __name__ == '__main__':
    run()
