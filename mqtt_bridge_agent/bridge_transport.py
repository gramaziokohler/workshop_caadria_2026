"""External MQTT "face" of the bridge agent.

This module owns all MQTT mechanics for talking to the external system.
It knows nothing about Antikythera tasks or agent lifecycle.
"""

from __future__ import annotations

import threading
import time
from abc import ABC
from abc import abstractmethod
from typing import Optional

from compas_eve import Message
from compas_eve import Publisher
from compas_eve import Subscriber
from compas_eve import Topic
from compas_eve.codecs import JsonMessageCodec
from compas_eve.mqtt import MqttTransport

_POLL_INTERVAL = 0.05  # seconds between cancellation / timeout checks


# ---------------------------------------------------------------------------
# Transport interface – the only contract the agent side depends on
# ---------------------------------------------------------------------------


class BridgeTransport(ABC):
    """Contract between the Antikythera agent and the external system."""

    @abstractmethod
    def send_and_wait(
        self,
        payload: dict,
        timeout: Optional[float] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict:
        """Deliver *payload* to the external system and block until a response arrives.

        Parameters
        ----------
        payload:
            Arbitrary key/value data to send.
        timeout:
            Maximum seconds to wait for a response.  ``None`` means wait forever.
        cancel_event:
            When set, the call raises ``InterruptedError`` immediately.

        Returns
        -------
        dict
            Response payload from the external system.

        Raises
        ------
        TimeoutError
            If *timeout* expires before a response arrives.
        InterruptedError
            If *cancel_event* is set before a response arrives.
        """

    @abstractmethod
    def close(self) -> None:
        """Release transport resources."""


# ---------------------------------------------------------------------------
# MQTT implementation
# ---------------------------------------------------------------------------


class ExternalMqttTransport(BridgeTransport):
    """Talks to an external system over MQTT using plain JSON.

    Publishes outbound messages to *publish_topic* and waits for an
    inbound response on *receive_topic*.  Concurrent calls are serialised
    by an internal lock so the external protocol stays request/response.
    """

    def __init__(
        self,
        broker_host: str,
        broker_port: int,
        publish_topic: str,
        receive_topic: str,
    ) -> None:
        transport = MqttTransport(host=broker_host, port=broker_port, codec=JsonMessageCodec())
        self._publisher = Publisher(Topic(publish_topic), transport=transport)
        self._subscriber = Subscriber(Topic(receive_topic), self._on_response, transport=transport)
        self._subscriber.subscribe()

        self._request_lock = threading.Lock()
        self._response_event = threading.Event()
        self._response: Optional[dict] = None

    # ------------------------------------------------------------------
    # BridgeTransport implementation
    # ------------------------------------------------------------------

    def send_and_wait(
        self,
        payload: dict,
        timeout: Optional[float] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> dict:
        with self._request_lock:
            self._response = None
            self._response_event.clear()
            self._publisher.publish(Message(**payload))
            return self._wait(timeout, cancel_event)

    def close(self) -> None:
        self._subscriber.unsubscribe()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _on_response(self, message: Message) -> None:
        self._response = dict(message.data)
        self._response_event.set()

    def _wait(
        self,
        timeout: Optional[float],
        cancel_event: Optional[threading.Event],
    ) -> dict:
        deadline = time.monotonic() + timeout if timeout is not None else None
        while True:
            if self._response_event.wait(timeout=_POLL_INTERVAL):
                return self._response  # type: ignore[return-value]
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("Task was cancelled while waiting for external response")
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for response from external system")
