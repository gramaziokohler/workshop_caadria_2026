"""Standalone entry point for the MQTT Bridge Agent.

Wires up an ExternalMqttTransport and an MqttBridgeAgent, then starts
an Antikythera AgentLauncher that routes tasks to the bridge.

Usage
-----
python -m mqtt_bridge_agent \\
    --broker-host  127.0.0.1 \\
    --broker-port  1883 \\
    --publish-topic bridge/request \\
    --receive-topic bridge/response \\
    --response-timeout 30
"""

from __future__ import annotations

import argparse
import logging
import time

from antikythera_agents.launcher import AgentLauncher

from .bridge_agent import MqttBridgeAgent
from .bridge_transport import ExternalMqttTransport

_AGENT_KEY = "mqtt_bridge"
LOG = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MQTT Bridge Agent launcher")
    p.add_argument("--broker-host", default="127.0.0.1", help="Antikythera MQTT broker host")
    p.add_argument("--broker-port", type=int, default=1883, help="Antikythera MQTT broker port")
    p.add_argument("--publish-topic", default="bridge/request", dest="publish_topic", help="Topic for outbound messages to the external system")
    p.add_argument("--receive-topic", default="bridge/response", dest="receive_topic", help="Topic for inbound responses from the external system")
    p.add_argument("--response-timeout", type=float, default=30.0, dest="response_timeout", help="Seconds to wait for a response from the external system")
    return p.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")
    args = _parse_args()

    transport = ExternalMqttTransport(
        broker_host=args.broker_host,
        broker_port=args.broker_port,
        publish_topic=args.publish_topic,
        receive_topic=args.receive_topic,
    )
    agent = MqttBridgeAgent(transport, response_timeout=args.response_timeout)

    launcher = AgentLauncher(broker_host=args.broker_host, broker_port=args.broker_port)
    launcher.agents[_AGENT_KEY] = agent
    launcher.start()

    LOG.info(
        "MQTT Bridge Agent running | publish → '%s' | receive ← '%s' | timeout %.1fs | Ctrl-C to stop",
        args.publish_topic,
        args.receive_topic,
        args.response_timeout,
    )

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        launcher.stop()
        LOG.info("Stopped.")


if __name__ == "__main__":
    main()
