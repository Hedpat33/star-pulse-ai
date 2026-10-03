"""Tests for notify.channels.feishu."""

import json
import unittest
from unittest import mock

import requests

from notify.channels import ChannelError, FeishuChannel, compute_sign
from notify.messages import CardMessage, PostMessage, RawCardMessage, TextMessage

URL = "https://open.feishu.cn/open-apis/bot/v2/hook/test-hook"


class ComputeSignTest(unittest.TestCase):
    """Vectors precomputed with the official algorithm: HMAC-SHA256 over
    an empty message, key = timestamp + newline + secret, then Base64."""

    def test_known_vector_one(self):
        self.assertEqual(
            compute_sign("1599360473", "my_secret"),
            "c0TNTtKsBgnsDysKO0jTMJg6H9S8NhkiTU1YPKJKRgs=",
        )

    def test_known_vector_two(self):
        self.assertEqual(
            compute_sign("1700000000", "other-secret"),
            "CsekdnVRew3Kc6cuploXuJbf2RUxbZ21emZTOmVTN9s=",
        )

    def test_sign_is_ascii(self):
        compute_sign("1599360473", "my_secret").encode("ascii")  # must not raise


class FromConfigTest(unittest.TestCase):
    def test_builds_channel(self):
        ch = FeishuChannel.from_config({"webhook_url": URL, "secret": "s3"})
        self.assertEqual(ch.webhook_url, URL)
        self.assertEqual(ch.secret, "s3")

    def test_secret_is_optional(self):
        ch = FeishuChannel.from_config({"webhook_url": URL})
        self.assertIsNone(ch.secret)

    def test_empty_secret_becomes_none(self):
        ch = FeishuChannel.from_config({"webhook_url": URL, "secret": ""})
        self.assertIsNone(ch.secret)

    def test_missing_url_rejected(self):
        with self.assertRaises(ValueError):
            FeishuChannel.from_config({})
        with self.assertRaises(ValueError):
            FeishuChannel.from_config({"webhook_url": "   "})

    def test_non_string_url_rejected(self):
        with self.assertRaises(ValueError):
            FeishuChannel.from_config({"webhook_url": 123})


class PrepareTest(unittest.TestCase):
    def test_injects_timestamp_and_sign(self):
        ch = FeishuChannel(URL, secret="my_secret")
        with mock.patch("notify.channels.feishu.time.time", return_value=1599360473.7):
            payload = ch._prepare({"msg_type": "text"})
        self.assertEqual(payload["timestamp"], "1599360473")
        self.assertEqual(
            payload["sign"], "c0TNTtKsBgnsDysKO0jTMJg6H9S8NhkiTU1YPKJKRgs="
        )

    def test_original_payload_not_mutated(self):
        ch = FeishuChannel(URL, secret="my_secret")
        payload = {"msg_type": "text"}
        with mock.patch("notify.channels.feishu.time.time", return_value=1.0):
            prepared = ch._prepare(payload)
        self.assertNotIn("sign", payload)
        self.assertIn("sign", prepared)

    def test_no_sign_without_secret(self):
        ch = FeishuChannel(URL)
        prepared = ch._prepare({"msg_type": "text"})
        self.assertNotIn("sign", prepared)
        self.assertNotIn("timestamp", prepared)


class RenderTextTest(unittest.TestCase):
    def setUp(self):
        self.ch = FeishuChannel(URL)

    def test_plain_text(self):
        payload = self.ch.render(TextMessage(text="hello"))
        self.assertEqual(payload, {"msg_type": "text", "content": {"text": "hello"}})

    def test_mentions_appended(self):
        payload = self.ch.render(
            TextMessage(text="hi", mentions=["ou_a", "ou_b"])
        )
        self.assertEqual(
            payload["content"]["text"],
            'hi <at user_id="ou_a">ou_a</at> <at user_id="ou_b">ou_b</at>',
        )

    def test_mention_all(self):
        payload = self.ch.render(TextMessage(text="hi", mention_all=True))
        self.assertEqual(
            payload["content"]["text"], 'hi <at user_id="all">所有人</at>'
        )

    def test_unsupported_type_returns_none(self):
        class Unknown:
            pass

        self.assertIsNone(self.ch.render(Unknown()))


class RenderPostTest(unittest.TestCase):
    def setUp(self):
        self.ch = FeishuChannel(URL)

    def test_plain_lines(self):
        payload = self.ch.render(PostMessage(title="Board", lines=["a", "b"]))
        zh = payload["content"]["post"]["zh_cn"]
        self.assertEqual(payload["msg_type"], "post")
        self.assertEqual(zh["title"], "Board")
        self.assertEqual(zh["content"], [[{"tag": "text", "text": "a"}],
                                         [{"tag": "text", "text": "b"}]])

    def test_line_with_link_splits_nodes(self):
        payload = self.ch.render(
            PostMessage(lines=["see [docs](https://example.com/x) now"])
        )
        nodes = payload["content"]["post"]["zh_cn"]["content"][0]
        self.assertEqual(
            nodes,
            [
                {"tag": "text", "text": "see "},
                {"tag": "a", "text": "docs", "href": "https://example.com/x"},
                {"tag": "text", "text": " now"},
            ],
        )

    def test_line_that_is_only_a_link(self):
        payload = self.ch.render(PostMessage(lines=["[home](https://a.io)"]))
        nodes = payload["content"]["post"]["zh_cn"]["content"][0]
        self.assertEqual(nodes, [{"tag": "a", "text": "home", "href": "https://a.io"}])

    def test_plain_line_keeps_unicode(self):
        payload = self.ch.render(PostMessage(lines=["星榜"]))
        self.assertEqual(
            payload["content"]["post"]["zh_cn"]["content"],
            [[{"tag": "text", "text": "星榜"}]],
        )


class RenderCardTest(unittest.TestCase):
    def setUp(self):
        self.ch = FeishuChannel(URL)

    def test_card_structure(self):
        payload = self.ch.render(
            CardMessage(title="Today", body="**top**", color="green")
        )
        self.assertEqual(payload["msg_type"], "interactive")
        card = payload["card"]
        self.assertEqual(card["schema"], "2.0")
        self.assertEqual(
            card["header"],
            {"title": {"tag": "plain_text", "content": "Today"}, "template": "green"},
        )
        self.assertEqual(
            card["body"]["elements"], [{"tag": "markdown", "content": "**top**"}]
        )

    def test_buttons_rendered_as_open_url(self):
        payload = self.ch.render(
            CardMessage(
                title="T",
                body="B",
                buttons=[("Open", "https://example.com/board")],
            )
        )
        elements = payload["card"]["body"]["elements"]
        self.assertEqual(elements[1]["tag"], "button")
        self.assertEqual(elements[1]["text"], {"tag": "plain_text", "content": "Open"})
        self.assertEqual(
            elements[1]["behaviors"],
            [{"type": "open_url", "default_url": "https://example.com/board"}],
        )


class RenderRawCardTest(unittest.TestCase):
    def test_raw_card_passthrough(self):
        ch = FeishuChannel(URL)
        card = {"schema": "2.0", "body": {"elements": []}}
        payload = ch.render(RawCardMessage(card=card))
        self.assertEqual(
            payload, {"msg_type": "interactive", "card": card}
        )

    def test_raw_card_send_payload(self):
        ch = FeishuChannel(URL)
        card = {"schema": "2.0", "body": {"elements": []}}
        with mock.patch(
            "notify.channels.feishu.requests.post",
            return_value=make_response({"code": 0}),
        ) as post:
            ch.send(RawCardMessage(card=card))
        body = json.loads(post.call_args.kwargs["data"].decode("utf-8"))
        self.assertEqual(body["msg_type"], "interactive")
        self.assertEqual(body["card"], card)


def make_response(payload: dict) -> mock.Mock:
    resp = mock.Mock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


class PostTest(unittest.TestCase):
    def test_successful_post_sends_json_body(self):
        ch = FeishuChannel(URL, secret="my_secret")
        body = json.dumps({"msg_type": "text"}).encode("utf-8")
        with mock.patch(
            "notify.channels.feishu.requests.post",
            return_value=make_response({"code": 0, "msg": "success"}),
        ) as post:
            result = ch._post(body)
        self.assertEqual(result["code"], 0)
        args, kwargs = post.call_args
        self.assertEqual(args[0], URL)
        self.assertEqual(kwargs["data"], body)
        self.assertEqual(kwargs["headers"], {"Content-Type": "application/json"})
        self.assertEqual(kwargs["timeout"], 10)

    def test_error_code_raises_with_hint(self):
        ch = FeishuChannel(URL, secret="s")
        with mock.patch(
            "notify.channels.feishu.requests.post",
            return_value=make_response(
                {"code": 19021, "msg": "sign match fail or timestamp is not "
                "within one hour from current time"}
            ),
        ):
            with self.assertRaises(ChannelError) as ctx:
                ch._post(b"{}")
        self.assertEqual(ctx.exception.code, 19021)
        self.assertIn("check server clock", str(ctx.exception))

    def test_unknown_error_code_has_no_hint(self):
        ch = FeishuChannel(URL)
        with mock.patch(
            "notify.channels.feishu.requests.post",
            return_value=make_response({"code": 42, "msg": "weird"}),
        ):
            with self.assertRaises(ChannelError) as ctx:
                ch._post(b"{}")
        self.assertEqual(ctx.exception.code, 42)
        self.assertIsNone(ctx.exception.hint)

    def test_network_error_wrapped(self):
        ch = FeishuChannel(URL)
        with mock.patch(
            "notify.channels.feishu.requests.post",
            side_effect=requests.ConnectionError("refused"),
        ):
            with self.assertRaises(ChannelError) as ctx:
                ch._post(b"{}")
        self.assertIsNone(ctx.exception.code)
        self.assertIn("request failed", str(ctx.exception))

    def test_invalid_json_response_wrapped(self):
        ch = FeishuChannel(URL)
        resp = mock.Mock()
        resp.raise_for_status.return_value = None
        resp.json.side_effect = ValueError("no json")
        with mock.patch("notify.channels.feishu.requests.post", return_value=resp):
            with self.assertRaises(ChannelError) as ctx:
                ch._post(b"{}")
        self.assertIn("invalid JSON", str(ctx.exception))


class SendEndToEndTest(unittest.TestCase):
    """send() drives render -> sign -> serialize -> post without network."""

    def test_text_send_full_payload(self):
        ch = FeishuChannel(URL, secret="my_secret")
        with mock.patch(
            "notify.channels.feishu.requests.post",
            return_value=make_response({"code": 0}),
        ) as post:
            ch.send(TextMessage(text="hello"))
        body = json.loads(post.call_args.kwargs["data"].decode("utf-8"))
        self.assertEqual(body["msg_type"], "text")
        self.assertEqual(body["content"], {"text": "hello"})
        self.assertIn("timestamp", body)
        self.assertEqual(
            body["sign"], compute_sign(body["timestamp"], "my_secret")
        )

    def test_card_send_payload(self):
        ch = FeishuChannel(URL)
        with mock.patch(
            "notify.channels.feishu.requests.post",
            return_value=make_response({"code": 0}),
        ) as post:
            ch.send(CardMessage(title="T", body="B"))
        body = json.loads(post.call_args.kwargs["data"].decode("utf-8"))
        self.assertEqual(body["msg_type"], "interactive")
        self.assertNotIn("sign", body)

    def test_post_send_payload(self):
        ch = FeishuChannel(URL)
        with mock.patch(
            "notify.channels.feishu.requests.post",
            return_value=make_response({"code": 0}),
        ) as post:
            ch.send(PostMessage(title="T", lines=["line"]))
        body = json.loads(post.call_args.kwargs["data"].decode("utf-8"))
        self.assertEqual(body["msg_type"], "post")
        self.assertEqual(
            body["content"]["post"]["zh_cn"]["content"],
            [[{"tag": "text", "text": "line"}]],
        )


if __name__ == "__main__":
    unittest.main()
