"""Antikythera "face" of the bridge agent.

This module owns all Antikythera task mechanics.
It knows nothing about MQTT topics or JSON encoding — it only speaks
the BridgeTransport abstraction.
"""

from __future__ import annotations

import threading
from typing import Any
from typing import Dict

from antikythera.models import Task
from antikythera_agents.base_agent import Agent
from antikythera_agents.context import ExecutionContext
from antikythera_agents.decorators import tool

from .bridge_transport import BridgeTransport


class MqttBridgeAgent(Agent):
    """Agent that delegates task execution to an external system via a BridgeTransport.

    Handles tasks of type ``<any_prefix>.call``.  Task inputs are packaged into
    a dict payload, sent to the external system, and the response keys that
    match declared task outputs are returned.

    The agent is intentionally unaware of MQTT, topics, or JSON — those details
    live entirely in the transport implementation.
    """

    def __init__(self, transport: BridgeTransport, response_timeout: float = 30.0) -> None:
        super().__init__()
        self._transport = transport
        self._response_timeout = response_timeout

    # ------------------------------------------------------------------
    # Tool
    # ------------------------------------------------------------------

    @tool(name="call")
    def call_external(self, task: Task, context: ExecutionContext) -> Dict[str, Any]:
        """Forward task inputs to the external system and return the response as outputs."""
        payload = {inp.name: inp.value for inp in task.inputs}

        cancel_event = threading.Event()
        context.on_cancel(cancel_event.set)

        response = self._transport.send_and_wait(
            payload,
            timeout=self._response_timeout,
            cancel_event=cancel_event,
        )

        declared_outputs = {out.name for out in task.outputs}
        return {key: value for key, value in response.items() if key in declared_outputs}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def dispose(self) -> None:
        self._transport.close()
        super().dispose()
