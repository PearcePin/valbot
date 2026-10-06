import json

from linebot.v3.messaging import (ApiClient, Configuration, MessagingApi, FlexMessage, FlexContainer,
                                   ReplyMessageRequest, PushMessageRequest, SetWebhookEndpointRequest,
                                   TestWebhookEndpointRequest)


class LineClient:
    def __init__(self, token: str):
        self.configuration = Configuration(access_token=token)

    @staticmethod
    def models(messages):
        return [FlexMessage(alt_text=x["altText"], contents=FlexContainer.from_json(json.dumps(x["contents"])))
                for x in messages]

    def validate_token(self):
        with ApiClient(self.configuration) as client:
            return MessagingApi(client).get_bot_info(_request_timeout=15)

    def validate_user(self, user_id):
        with ApiClient(self.configuration) as client:
            return MessagingApi(client).get_profile(user_id, _request_timeout=15)

    def configure_webhook(self, endpoint):
        """Verify the new endpoint before replacing the existing LINE webhook."""
        with ApiClient(self.configuration) as client:
            api = MessagingApi(client)
            test = api.test_webhook_endpoint(TestWebhookEndpointRequest(endpoint=endpoint), _request_timeout=20)
            if not test.success:
                raise RuntimeError("LINE 無法驗證新 Webhook，現有設定未變更。")
            api.set_webhook_endpoint(SetWebhookEndpointRequest(endpoint=endpoint), _request_timeout=15)
            state = api.get_webhook_endpoint(_request_timeout=15)
            if state.endpoint != endpoint:
                raise RuntimeError("LINE Webhook 網址未更新成功。")
            return state.active

    def reply(self, reply_token, messages):
        with ApiClient(self.configuration) as client:
            MessagingApi(client).reply_message(ReplyMessageRequest(reply_token=reply_token,
                                                 messages=self.models(messages[:5])), _request_timeout=15)

    def push(self, user_id, messages, retry_key):
        if not 1 <= len(messages) <= 5:
            raise ValueError("一次推播必須包含 1 至 5 則訊息。")
        with ApiClient(self.configuration) as client:
            MessagingApi(client).push_message(PushMessageRequest(to=user_id, messages=self.models(messages)),
                                              x_line_retry_key=retry_key, _request_timeout=20)
