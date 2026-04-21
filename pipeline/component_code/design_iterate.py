"""Helper to iterate a blueprint session by resetting a task and resuming.

Calls three existing antikythera API endpoints in sequence:
pause -> reset task (+ downstream) -> start.
"""

import json
import urllib.error
import urllib.request


def iterate_session(api_url, session_id, blueprint_id, task_id):
    """Reset *task_id* and all downstream tasks, then resume the session.

    Parameters
    ----------
    api_url : str
        Orchestrator REST API base URL, e.g. ``http://localhost:8000``.
    session_id : str
        Active blueprint session ID.
    blueprint_id : str
        Blueprint ID within the session (e.g. ``caadria-dfab``).
    task_id : str
        Task to reset (e.g. ``design``).  All downstream tasks are also reset.

    Returns
    -------
    dict
        Response from the final ``start`` call, or an error dict.
    """
    # 1. Pause — ignore errors (session may already be stopped/completed)
    _post(api_url, f"/sessions/{session_id}/pause")

    # 2. Reset task + downstream, clear outputs
    reset_resp = _post(
        api_url,
        f"/sessions/{session_id}/tasks/reset",
        payload={
            "blueprint_id": blueprint_id,
            "task_id": task_id,
            "include_downstream": True,
            "clear_outputs": True,
        },
    )
    if "error" in reset_resp:
        return reset_resp

    # 3. Resume session
    start_resp = _post(
        api_url,
        f"/sessions/{session_id}/start",
        payload={},
    )
    return start_resp


def _post(api_url, path, payload=None):
    """Fire a POST request and return the parsed JSON response (or error dict)."""
    url = f"{api_url.rstrip('/')}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else b"{}"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {body}"}
    except urllib.error.URLError as e:
        return {"error": str(e)}
