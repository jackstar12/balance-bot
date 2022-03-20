import argparse
import json
import logging
import shutil

import dotenv
dotenv.load_dotenv()
from datetime import datetime, timedelta
import config
from api.app import app
from api.database import db
from api.dbmodels.balance import balance_from_json
from api.dbmodels.client import Client
from api.dbmodels.discorduser import add_user_from_json, DiscordUser
from api.dbmodels.event import Event
from api.dbmodels.archive import Archive
from config import DATA_PATH

parser = argparse.ArgumentParser(description="Run the bot.")
parser.add_argument("-e", "--event", action="store_true", help="Specifying this creates an dev event which can be used")
parser.add_argument("-u", "--users", action="store_true", help="Specifying this puts the users.json the database.")
parser.add_argument("-d", "--data", action="store_true", help="Specifying this puts the current data into a database.")
parser.add_argument("-a", "--archive", action="store_true", help="Create archive for old events")

args = parser.parse_args()


if args.archive:
    shutil.copy("HISTORY_443583326507499520_704403630375305317_1643670000.png", DATA_PATH + "HISTORY_443583326507499520_704403630375305317_1643670000.png")
    now = datetime.now()
    event = Event.query.first()
    archive = Archive(
        event_id=event.id,
        registrations=
        """
loopy
jacksn
Arygon
Moket ⚡
CryptoBRO
0xOase13
None
Knockkek
Redslim
beat
Escaliert
Bitcoin_Gamer_21
1893
undercover
Mr888 | ∆ L∑X
        """,
        leaderboard=
        """
Gain since start

1. 1893 133.97% (42.95$)
2. Knockkek 59.74% (59.74$)
3. Redslim 42.36% (42.36$)
4. jacksn 37.06% (18.53$)
5. undercover 30.76% (30.76$)
6. Bitcoin_Gamer_21 18.88% (16.23$)
7. loopy 8.56% (18.72$)
8. Mr888 | ∆ L∑X -3.01% (-301.44$)
9. Moket ⚡ -59.18% (-110.67$)
10. beat -94.35% (-94.35$)

Rekt
CryptoBRO since 2022-02-19 00:00:00
Escaliert since 2022-02-18 02:00:00
Arygon since 2022-03-01 16:35:12
        """,
        summary=
        """
Best Trader :crown:
1893

Worst Trader :disappointed_relieved:
Escaliert

Highest Stakes :moneybag:
Mr888 | ∆ L∑X

Most Degen Trader :grimacing:
CryptoBRO

Still HODLing :sleeping:
loopy

Last but not least...
In total you lost -535.92$
Cumulative % performance: -10.39%
        """,
        history_path="HISTORY_443583326507499520_704403630375305317_1643670000.png"
    )
    db.session.add(archive)
    db.session.commit()


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
                        user = DiscordUser.query.filter_by(user_id=user_id).first()
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
        name="Challenge",
        description="February challenge",
        guild_id=443583326507499520,
        channel_id=704403630375305317,
        registrations=Client.query.all(),
        start=datetime(year=2022, month=2, day=1),
        end=datetime(year=2022, month=3, day=1),
        registration_start=datetime(year=2022, month=1, day=25),
        registration_end=datetime(year=2022, month=2, day=5)
    )
    db.session.add(event)
    db.session.commit()

    print('Created dev event. Do not run this again to avoid duplication')
