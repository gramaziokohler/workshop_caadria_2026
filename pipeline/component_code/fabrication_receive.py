# r: compas==2.15.1, timber_design==0.2.0, compas_eve
# venv: akt_agent

"""Fabrication Receiver — fabrication.gh

Listens for a 'fabrication.toolpaths' task from the orchestrator.
Outputs the TimberModel and task metadata for downstream toolpath generation.

Use the companion Fabrication Submit component to send computed toolpaths
back once they have been reviewed and approved. The two components share the
BackgroundWorker via sc.sticky keyed on task_type to avoid a GH loop.
"""

from compas_rhino.devtools import DevTools

DevTools.ensure_path()

import Grasshopper
import scriptcontext as sc

from compas_eve.ghpython import BackgroundWorker
from gh_agent import run_agent, stop_agent

DEFAULT_TASK_TYPE = "fabrication.toolpaths"


class FabricationReceiverComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, task_type: str, broker_host: str, broker_port: int, enabled):
        print("ran!")
        broker_host = broker_host or "127.0.0.1"
        broker_port = int(broker_port) if broker_port else 1883
        task_type = task_type or DEFAULT_TASK_TYPE
        # print(sc.sticky)
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

        # if assigned task by antikythera
        if pending_task:
            # we got assigned a task by the orchestrator
            ghenv.Component.Message = "task received — generate toolpaths!"  # noqa: F821
            return pending_task

        ghenv.Component.Message = "listening"  # noqa: F821
        return None
