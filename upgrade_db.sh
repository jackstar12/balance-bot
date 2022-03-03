export FLASK_APP='api/app.py'
flask db init
flask db migrate
flask db upgrade
