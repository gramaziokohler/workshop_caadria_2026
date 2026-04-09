# r: compas_timber, compas_fab, compas_robots, compas_eve, antikythera, antikythera_agents
# venv: akt_agent
"""Robot Agent — robot.gh

Listens for a 'robot.mill' task from the orchestrator.
When a task arrives the approved toolpaths from the Fabrication agent are
available on the `toolpaths` output — wire them into your robot execution logic.

This agent is intended to be fully automatic: as soon as the toolpaths arrive
the robot script runs, and when execution is done the component submits a
milling report back automatically (set `submit` to a boolean expression that
reflects whether execution completed, e.g. the output of your robot driver).

For workshop safety the `submit` input is left manual so a facilitator can
verify before actually running the robot.
"""

import Grasshopper
import scriptcontext as sc

from compas_eve.ghpython import BackgroundWorker
from gh_agent import run_agent, stop_agent, submit_result

DEFAULT_TASK_TYPE = "robot.mill"


class RobotAgentComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        task_type: str,
        broker_host: str,
        broker_port: int,
        enabled,
        milling_report,
        submit,
    ):
        broker_host = broker_host or "127.0.0.1"
        broker_port = int(broker_port) if broker_port else 1883
        task_type = task_type or DEFAULT_TASK_TYPE

        # ── Stop ──────────────────────────────────────────────────────────────
        if not enabled:
            BackgroundWorker.stop_instance_by_component(ghenv)  # noqa: F821
            ghenv.Component.Message = "disabled"  # noqa: F821
            return None, None, None, None, "disabled"

        # ── Config-change detection ───────────────────────────────────────────
        config = (task_type, broker_host, broker_port)
        config_key = "akt_robot_config_{}".format(ghenv.Component.InstanceGuid)  # noqa: F821
        config_changed = sc.sticky.get(config_key) != config
        sc.sticky[config_key] = config

        # ── BackgroundWorker ──────────────────────────────────────────────────
        worker = BackgroundWorker.instance_by_component(
            ghenv,  # noqa: F821
            lambda w, tt=task_type, bh=broker_host, bp=broker_port: run_agent(self, w, tt, bh, bp, "RobotAgent"),
            dispose_function=stop_agent,
            auto_set_done=False,
            force_new=config_changed,
        )

        if not worker.is_working() and not worker.is_done():
            worker.start_work()
            ghenv.Component.Message = "starting…"  # noqa: F821
            return None, None, None, None, "starting"

        # ── Submit ────────────────────────────────────────────────────────────
        pending = getattr(worker, "pending_task", None)

        if submit and milling_report is not None and pending:
            submit_result(worker, {"milling_report": milling_report})
            ghenv.Component.Message = "listening"  # noqa: F821
            return None, None, None, None, "submitted"

        # ── Expose task data: toolpaths come in via inputs ────────────────────
        if pending:
            toolpaths = pending["inputs"].get("toolpaths")
            ghenv.Component.Message = "toolpaths received — ready to mill"  # noqa: F821
            return (
                pending["id"],
                toolpaths,
                pending["params"],
                pending["output_keys"],
                "task_received",
            )

        ghenv.Component.Message = "listening"  # noqa: F821
        return None, None, None, None, "listening"
