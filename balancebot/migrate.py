import argparse
import json
import logging
from datetime import datetime, timedelta

import balancebot.api.database as db
from balancebot.api.dbmodels.balance import balance_from_json
from balancebot.api.dbmodels.client import Client
from balancebot.api.dbmodels.discorduser import add_user_from_json, DiscordUser
from balancebot.api.dbmodels.event import Event
from sqlalchemy_utils.types.encrypted.encrypted_type import FernetEngine
import dotenv
import os
from balancebot.bot.config import DATA_PATH

dotenv.load_dotenv()

parser = argparse.ArgumentParser(description="Run the bot.")
parser.add_argument("-e", "--event", action="store_true", help="Specifying this creates an dev event which can be used")
parser.add_argument("-u", "--users", action="store_true", help="Specifying this puts the users.json the database.")
parser.add_argument("-d", "--data", action="store_true", help="Specifying this puts the current data into a database.")
parser.add_argument("-k", "--keys", action="store_true", help="Specifying this puts the current data into a database.")

args = parser.parse_args()


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


if args.users:
    try:
        with open(DATA_PATH + 'users.json', 'r') as f:
            users_json = json.load(fp=f)
            for user_json in users_json:
                try:
                    add_user_from_json(user_json)
                except KeyError as e:
                    logging.error(f'{e} occurred while parsing user data {user_json} from users.json')
    except FileNotFoundError:
        logging.info(f'No user information found')
    except json.decoder.JSONDecodeError:
        pass
    db.session.commit()

    print('Done migrating users. Do not run this again to avoid duplication')
if args.data:

    try:
        with open(DATA_PATH + "user_data.json", "r") as f:
            raw_json = json.load(fp=f)
            if raw_json:
                for ts, data in raw_json:
                    time = datetime.fromtimestamp(ts)
                    for user_id in data:
                        user = db.session.query(DiscordUser).filter_by(user_id=user_id).first()
                        if not user:
                            print(f'Got no discorduser with id {user_id}, creating dummy')
                            user = add_user_from_json({
                                'id': user_id,
                                'api_key': 'api_key',
                                'api_secret': 'api_secret',
                                'exchange': 'binance-futures',
                                'subaccount': '',
                                'extra': {}
                            })
                        for key in data[user_id].keys():
                            balance = balance_from_json(data[user_id][key], time)
                            user.global_client.history.append(balance)
                            db.session.add(balance)
                            break
    except FileNotFoundError:
        logging.info('No user data found')
    except json.JSONDecodeError as e:
        logging.error(f'{e}: Error while parsing user data.')

    db.session.commit()

    print('Done migrating. Do not run this again to avoid duplication')


if args.event:
    event = Event(
        name="Dev",
        description="dev event",
        guild_id=798957933135790091,
        channel_id=942495607015227502,
        registrations=Client.query.all(),
        start=datetime.fromtimestamp(0),
        end=datetime.now() + timedelta(days=23),
        registration_start=datetime.fromtimestamp(0),
        registration_end=datetime.now() + timedelta(days=24)
    )
    db.session.add(event)
    db.session.commit()

    print('Created dev event. Do not run this again to avoid duplication')
