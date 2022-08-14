# Starting

So how do you get this whole thing running?
Because of the way the architecture is built there are multiple ways. 
You can start every microservice on its own or all of them together. 

For this purpose, every service has its own `Dockerfile`. There is also a `docker-compose.yml` which can be used to get all of them
up and running quickly. Keep in mind that before starting any of those, the DB migrations should run.
The script `upgrade_db.sh` can be used in this case.

    sh upgrade_db.sh
    docker-compose up