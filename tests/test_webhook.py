import base64
import hashlib
import hmac
import json
import time
from unittest.mock import Mock

from fastapi.testclient import TestClient

from valbot.app import create_app
from valbot.queue import Inbox
from valbot.storage import Vault

SECRET = "channel-secret"
OWNER = "U" + "1" * 32


def signed(body):
    return base64.b64encode(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest()).decode()


def test_signature_and_owner_gate_and_unknown_menu(tmp_path):
    vault = Vault(tmp_path)
    line = Mock()
    app = create_app({"line_channel_secret": SECRET, "line_user_id": OWNER}, vault, line)
    with TestClient(app) as client:
        assert client.post("/webhook", content='{"events":[]}').status_code == 400
        body = json.dumps({"events": []})
        assert client.post("/webhook", content=body, headers={"x-line-signature": signed(body)}).status_code == 200
        event = {"type": "message", "timestamp": int(time.time() * 1000), "webhookEventId": "event-1",
                 "mode": "active", "deliveryContext": {"isRedelivery": False},
                 "replyToken": "reply", "source": {"type": "user", "userId": "U" + "2" * 32},
                 "message": {"type": "text", "id": "123", "text": "unknown", "quoteToken": "quote"}}
        body = json.dumps({"events": [event]})
        assert client.post("/webhook", content=body, headers={"x-line-signature": signed(body)}).status_code == 200
        assert app.state.inbox.claim() is None
        event["source"]["userId"] = OWNER
        body = json.dumps({"events": [event]})
        for _ in range(2):
            assert client.post("/webhook", content=body, headers={"x-line-signature": signed(body)}).status_code == 200
        deadline = time.monotonic() + 3
        while not line.reply.called and time.monotonic() < deadline:
            time.sleep(0.02)
        assert line.reply.call_count == 1
        assert line.reply.call_args.args[1][0]["contents"]["type"] == "bubble"


def test_inbox_survives_restart_and_hides_reply_token(tmp_path):
    vault = Vault(tmp_path)
    inbox = Inbox(vault)
    event = {"webhookEventId": "id", "replyToken": "private-reply-token"}
    inbox.enqueue(event)
    inbox.enqueue(event)
    restarted = Inbox(vault)
    assert restarted.claim() == ("id", event)
    assert b"private-reply-token" not in (tmp_path / "inbox.sqlite3").read_bytes()
    restarted.finish("id")
    assert inbox.claim() is None
