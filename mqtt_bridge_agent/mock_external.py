"""Mock external application that echoes bridge requests back as responses.

IronPython 2.7 compatible. Requires compas_eve 1.0.0.

Subscribes to the request topic, then publishes the same payload back
on the response topic unchanged.

Usage
-----
python mock_external.py \\
    --broker-host 127.0.0.1 \\
    --broker-port 1883 \\
    --request-topic bridge/request \\
    --response-topic bridge/response
"""

from __future__ import print_function

import argparse
import logging
import time

from compas_eve import Message
from compas_eve import Publisher
from compas_eve import Subscriber
from compas_eve import Topic
from compas_eve.mqtt import MqttTransport

LOG = logging.getLogger(__name__)


def _parse_args():
    p = argparse.ArgumentParser(description="Mock external system - echoes bridge requests")
    p.add_argument("--broker-host", default="127.0.0.1")
    p.add_argument("--broker-port", type=int, default=1883)
    p.add_argument("--request-topic", default="bridge/request", dest="request_topic")
    p.add_argument("--response-topic", default="bridge/response", dest="response_topic")
    return p.parse_args()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
    args = _parse_args()

    transport = MqttTransport(host=args.broker_host, port=args.broker_port)
    publisher = Publisher(Topic(args.response_topic), transport=transport)

    def on_request(message):
        payload = dict(message.data)
        LOG.info("Request  -> %s", payload)
        publisher.publish(Message(**payload))
        LOG.info("Response <- %s", payload)

    subscriber = Subscriber(Topic(args.request_topic), on_request, transport=transport)
    subscriber.subscribe()

    LOG.info(
        "Mock external app | request <- '%s' | response -> '%s' | Ctrl-C to stop",
        args.request_topic,
        args.response_topic,
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        subscriber.unsubscribe()
        LOG.info("Stopped.")


if __name__ == "__main__":
    main()
