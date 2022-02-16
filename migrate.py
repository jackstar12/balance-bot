import argparse
import json
import logging
from datetime import datetime, timedelta

from api.database import db
from api.dbmodels.balance import balance_from_json
from api.dbmodels.client import Client
from api.dbmodels.discorduser import add_user_from_json, DiscordUser
from api.dbmodels.event import Event
from config import DATA_PATH

parser = argparse.ArgumentParser(description="Run the bot.")
parser.add_argument("-e", "--event", action="store_true", help="Specifying this creates an dev event which can be used")
parser.add_argument("-u", "--users", action="store_true", help="Specifying this puts the users.json the database.")
parser.add_argument("-d", "--data", action="store_true", help="Specifying this puts the current data into a database.")
parser.add_subparsers()

args = parser.parse_args()


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

    print('Done migrating. Do not run this again to avoid duplication')
    exit()

if args.data:

    try:
        with open(DATA_PATH + "user_data.json", "r") as f:
            raw_json = json.load(fp=f)
            if raw_json:
                for ts, data in raw_json:
                    time = datetime.fromtimestamp(ts)
                    for user_id in data:
                        user = DiscordUser.query.filter_by(user_id=user_id).first()
                        if not user:
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
    exit()


if args.event:
    event = Event(
        name="Dev",
        description="dev event",
        guild_id=715507174167806042,
        channel_id=715507174167806045,
        registrations=Client.query.all(),
        start=datetime.fromtimestamp(0),
        end=datetime.now() + timedelta(days=23),
        registration_start=datetime.fromtimestamp(0),
        registration_end=datetime.now() + timedelta(days=24)
    )
    db.session.add(event)
    db.session.commit()

    print('Created dev event. Do not run this again to avoid duplication')
    exit()
