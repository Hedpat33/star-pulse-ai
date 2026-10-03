"""CLI entry point for sending messages from the command line."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from notify.channels import ChannelError, FeishuChannel, UnsupportedMessage
from notify.config import ConfigError, load_notify_config
from notify.messages import CardMessage, Message, PostMessage, TextMessage
from notify.messages.base import MessageTooLarge

logger = logging.getLogger("notify")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notify",
        description="Send a notification message through a configured channel.",
    )
    parser.add_argument("--channel", default="feishu", choices=("feishu",),
                        help="target channel (default: feishu)")
    parser.add_argument("--type", required=True, dest="msg_type",
                        choices=("text", "post", "card"),
                        help="message type to send")
    parser.add_argument("--text", default=None,
                        help="body text (required for --type text)")
    parser.add_argument("--title", default=None,
                        help="title (required for --type card, optional for post)")
    parser.add_argument("--body", default=None,
                        help="message body (post/card)")
    parser.add_argument("--body-file", default=None,
                        help="read body from a UTF-8 file (post/card)")
    parser.add_argument("--color", default="blue",
                        help="card header color (default: blue)")
    parser.add_argument("--button", action="append", default=[],
                        metavar="LABEL=URL",
                        help="card button; repeatable")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="enable DEBUG logging")
    return parser


def _read_body(args: argparse.Namespace) -> str:
    if args.body is not None and args.body_file is not None:
        raise ConfigError("--body and --body-file are mutually exclusive")
    if args.body_file is not None:
        try:
            return Path(args.body_file).read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"cannot read --body-file: {exc}") from exc
    if args.body is not None:
        return args.body
    raise ConfigError("one of --body or --body-file is required")


def build_message(args: argparse.Namespace) -> Message:
    """Turn parsed CLI args into a Message, raising ConfigError on misuse."""
    if args.msg_type == "text":
        if not args.text:
            raise ConfigError("--text is required for --type text")
        return TextMessage(text=args.text)

    body = _read_body(args)
    if not body.strip():
        raise ConfigError("message body is empty")

    if args.msg_type == "post":
        lines = [line for line in body.splitlines() if line.strip()]
        return PostMessage(title=args.title or "", lines=lines)

    if not args.title:
        raise ConfigError("--title is required for --type card")
    buttons: List[tuple] = []
    for spec in args.button:
        label, sep, url = spec.partition("=")
        if not sep or not label.strip() or not url.strip():
            raise ConfigError(
                f"invalid --button {spec!r}; expected 'LABEL=URL'"
            )
        buttons.append((label, url))
    return CardMessage(
        title=args.title, body=body, color=args.color, buttons=buttons
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )

    try:
        config = load_notify_config()
        if config is None:
            raise ConfigError("FEISHU_WEBHOOK_URL is not set")
        channel = FeishuChannel.from_config(config[args.channel])
        message = build_message(args)
        channel.send(message)
    except (ConfigError, ValueError, MessageTooLarge,
            UnsupportedMessage, ChannelError) as exc:
        logger.error("%s", exc)
        return 1

    logger.info("sent %s message via %s", args.msg_type, args.channel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
