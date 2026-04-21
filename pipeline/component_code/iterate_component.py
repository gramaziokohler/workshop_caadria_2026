# r: compas==2.15.1, timber_design==0.2.0, compas_eve
# venv: akt_agent
# env: /Users/chenkasirer/repos/GKR/workshop_caadria_2026/grasshopper/pipeline
"""Iterate — reset the design task and resume the session.

Place this component in design.gh alongside the Design Agent.
Wire in the ``session_id`` from AKT_Start_Blueprint.
Pulse ``iterate`` after the pipeline has completed (or while running)
to reset the design task and all downstream tasks, then resume.
"""

import json
import urllib.error
import urllib.request

import Grasshopper

BLUEPRINT_ID = "caadria-dfab"
TASK_ID = "design"


class IterateComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, session_id: str, api_url: str, iterate):
        api_url = api_url or "http://localhost:8000"

        if not iterate:
            return "ready"

        if not session_id:
            ghenv.Component.Message = "no session"  # noqa: F821
            return "error: no session_id"

        ghenv.Component.Message = "iterating..."  # noqa: F821

        # 1. Pause (ignore errors — session may already be stopped/completed)
        _post(api_url, f"/sessions/{session_id}/pause")

        # 2. Reset design task + downstream
        reset = _post(
            api_url,
            f"/sessions/{session_id}/tasks/reset",
            payload={
                "blueprint_id": BLUEPRINT_ID,
                "task_id": TASK_ID,
                "include_downstream": True,
                "clear_outputs": True,
            },
        )
        if "error" in reset:
            ghenv.Component.Message = "reset failed"  # noqa: F821
            return f"error: {reset['error']}"

        # 3. Resume
        start = _post(api_url, f"/sessions/{session_id}/start", payload={})
        if "error" in start:
            ghenv.Component.Message = "start failed"  # noqa: F821
            return f"error: {start['error']}"

        ghenv.Component.Message = "iterated!"  # noqa: F821
        return "iterated"


def _post(api_url, path, payload=None):
    url = f"{api_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else b"{}"
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {body}"}
    except urllib.error.URLError as e:
        return {"error": str(e)}
