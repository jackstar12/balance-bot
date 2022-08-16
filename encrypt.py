import argparse
import os
import dotenv
from sqlalchemy_utils.types.encrypted.encrypted_type import FernetEngine

dotenv.load_dotenv()

parser = argparse.ArgumentParser(description="Run the bot.")
parser.add_argument("--secret", help="Encrypt an api secret")

args = parser.parse_args()

if args.secret:
    engine = FernetEngine()

    _key = os.environ.get('ENCRYPTION_SECRET')
    assert _key, 'Missing ENCRYPTION_SECRET in env'

    engine._update_key(_key)

    print(engine.encrypt(args.secret))
