"""One-shot scheduled push, restart-safe with LINE retry keys and per-day checkpoints."""
import argparse
from datetime import datetime
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import uuid

import httpx
from linebot.v3.messaging.exceptions import ApiException

from valbot.auth import RiotAuth
from valbot.line import LineClient
from valbot.riot import RiotClient
from valbot.service import BotService
from valbot.storage import Vault, atomic_write, data_dir


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir")
    parser.add_argument("--dry-run", action="store_true", help="產生 Flex JSON，不傳送 LINE")
    parser.add_argument("--force", action="store_true", help="同一天重新推播（會使用新的 retry key）")
    args = parser.parse_args()
    if args.data_dir:
        os.environ["VALBOT_DATA_DIR"] = args.data_dir
    directory = data_dir()
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(directory / "daily.log",
                         maxBytes=1000000, backupCount=3, encoding="utf-8")],
                         format="%(asctime)s %(levelname)s %(message)s")
    try:
        vault = Vault()
        config = vault.read("config")
        if not config:
            raise RuntimeError("尚未設定")
        with vault.lock("daily"):
            day = datetime.now().astimezone().date().isoformat()
            checkpoint = vault.read("daily")
            target = hashlib.sha256(config["line_user_id"].encode()).hexdigest()
            if not args.dry_run and not args.force and checkpoint.get("date") == day \
                    and checkpoint.get("target") == target and checkpoint.get("done"):
                logging.info("Already delivered today's push")
                return 0
            if args.dry_run or args.force or checkpoint.get("date") != day or checkpoint.get("target") != target:
                with httpx.Client(timeout=15) as client:
                    messages = BotService(RiotClient(config, RiotAuth(vault), client)).daily()
                if args.dry_run:
                    atomic_write(directory / "daily-preview.json", json.dumps(messages, ensure_ascii=False,
                                 indent=2).encode())
                    return 0
                checkpoint = {"date": day, "target": target, "messages": messages,
                              "keys": [str(uuid.uuid4()) for _ in range(0, len(messages), 5)],
                              "sent": 0, "done": False}
                vault.write("daily", checkpoint)
            line = LineClient(config["line_access_token"])
            batches = [checkpoint["messages"][i:i + 5] for i in range(0, len(checkpoint["messages"]), 5)]
            for i in range(checkpoint["sent"], len(batches)):
                try:
                    line.push(config["line_user_id"], batches[i], checkpoint["keys"][i])
                except ApiException as exc:
                    headers = {str(k).lower(): v for k, v in (exc.headers or {}).items()}
                    if exc.status != 409 or not headers.get("x-line-accepted-request-id"):
                        raise
                    # A retry key already accepted by LINE is a successful delivery checkpoint.
                checkpoint["sent"] = i + 1
                vault.write("daily", checkpoint)
            checkpoint["done"] = True
            vault.write("daily", checkpoint)
            logging.info("Daily push delivered (%s messages)", len(checkpoint["messages"]))
        return 0
    except Exception as exc:
        logging.error("Daily push failed (%s). Check login, network and LINE quota.", type(exc).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
