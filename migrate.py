import argparse
from datetime import datetime, timedelta

import pytz
from sqlalchemy.orm import make_transient

import database.dbsync as db
from database.dbmodels.client import Client
from database.dbmodels.discord.discorduser import DiscordUser
from database.dbmodels.event import Event
from sqlalchemy_utils.types.encrypted.encrypted_type import FernetEngine
import dotenv
import os

from database.dbmodels.user import User

dotenv.load_dotenv()

parser = argparse.ArgumentParser(description="Run the test_bot.")
parser.add_argument("-e", "--event", action="store_true", help="Specifying this creates an dev event which can be used")
parser.add_argument("-u", "--users", action="store_true", help="Specifying this puts the users.json the database.")
parser.add_argument("-d", "--data", action="store_true", help="Specifying this puts the current data into a database.")
parser.add_argument("-k", "--keys", action="store_true", help="Specifying this puts the current data into a database.")
parser.add_argument("-c", "--discordids", action="store_true", help="Specifying this puts the migrates the discord user ids")
parser.add_argument("--uuid", action="store_true", help="Specifying this puts the migrates the discord user ids")

args = parser.parse_args()


if args.discordids:
    discord_users = db.session.query(DiscordUser).all()

    for discord_user in discord_users:
        db.session.add(discord_user)
        make_transient(discord_user)
        discord_user.channel_id = discord_user.USER_ID
        db.session.add(discord_user)

    db.session.commit()

    discord_users = db.session.query(DiscordUser).all()

    users = db.session.query(User).all()
    for user in users:
        user.discord_user_id = user.discord_user.USER_ID

    for client in db.session.query(Client).all():
        if client.discord_user:
            client.discord_user_id = client.discord_user.USER_ID

    db.session.commit()

    db.session.query(DiscordUser).filter(DiscordUser.id != DiscordUser.user_id).delete()
    db.session.commit()
    print('Migrated discorduser ids')

if args.keys:
    clients = db.session.query(Client).all()
    _key = os.environ.get('ENCRYPTION_SECRET')
    assert _key, 'Missing ENCRYPTION_SECRET env'

    engine = FernetEngine()
    engine._update_key(_key)

    for client in clients:
        client.api_secret = engine.encrypt(client.api_secret)
    db.session.commit()
    print('Encrypted API Keys')



if args.event:
    event = Event(
        name="Dev",
        description="dev event",
        guild_id=798957933135790091,
        channel_id=942495607015227502,
        registrations=Client.query.all(),
        start=datetime.fromtimestamp(0),
        end=datetime.now(pytz.utc) + timedelta(days=23),
        registration_start=datetime.fromtimestamp(0),
        registration_end=datetime.now(pytz.utc) + timedelta(days=24)
    )
    db.session.add(event)
    db.session.commit()

    print('Created dev event. Do not run this again to avoid duplication')
