# r: compas==2.15.1, timber_design==0.2.0, compas_eve
# venv: akt_agent

"""Design Agent — design.gh

Listens for a 'design.compute' task from the orchestrator.
When a task arrives the component re-solves and exposes any orchestrator
params on the `params` output.  Wire your TimberModel into `timber_model`
and pulse `submit` when you are happy with the design.

The agent sends the model back to the orchestrator which stores it in the
session and forwards it to the Fabrication agent.
"""

from compas_rhino.devtools import DevTools

DevTools.ensure_path()

import Grasshopper
import scriptcontext as sc

from compas_eve.ghpython import BackgroundWorker
from gh_agent import run_agent, stop_agent

DEFAULT_TASK_TYPE = "design.compute"


class DesignAgentComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        task_type: str,
        broker_host: str,
        broker_port: int,
        enabled,
        timber_model,
        submit,
    ):
        broker_host = broker_host or "127.0.0.1"
        broker_port = int(broker_port) if broker_port else 1883
        task_type = task_type or DEFAULT_TASK_TYPE

        # ── Stop ──────────────────────────────────────────────────────────────
        if not enabled:
            BackgroundWorker.stop_instance_by_component(ghenv)  # noqa: F821
            ghenv.Component.Message = "disabled"  # noqa: F821
            return None

        # ── BackgroundWorker ──────────────────────────────────────────────────
        # listetning starts
        worker = BackgroundWorker.instance_by_component(
            ghenv,  # noqa: F821
            lambda w, tt=task_type, bh=broker_host, bp=broker_port: run_agent(
                w, tt, bh, bp, "FabricationAgent"
            ),
            dispose_function=stop_agent,
            auto_set_done=False,
        )

        if not worker.is_working() and not worker.is_done():
            worker.start_work()
            ghenv.Component.Message = "starting…"  # noqa: F821
            return None

        # ── Expose task data ───────────────────────────────────────────────────
        pending_task = getattr(worker, "pending_task", None)

        if submit and pending_task:
            pending_task.task_outputs = {"timber_model": timber_model}
            if pending_task.event:
                pending_task.event.set()

            ghenv.Component.Message = "submitted"  # noqa: F821
            return None

        # if assigned task by antikythera
        if pending_task:
            # we got assigned a task by the orchestrator
            ghenv.Component.Message = "task received — generate toolpaths!"  # noqa: F821
            return None

        ghenv.Component.Message = "listening"  # noqa: F821
        return None
