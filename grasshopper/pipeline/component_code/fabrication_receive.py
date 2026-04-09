# r: compas==2.15.1, timber_design==0.2.0, compas_eve
# venv: akt_agent
# env: /Users/chenkasirer/repos/GKR/workshop_caadria_2026/grasshopper/pipeline
"""Fabrication Receiver — fabrication.gh

Listens for a 'fabrication.toolpaths' task from the orchestrator.
Outputs the TimberModel and task metadata for downstream toolpath generation.

Use the companion Fabrication Submit component to send computed toolpaths
back once they have been reviewed and approved. The two components share the
BackgroundWorker via sc.sticky keyed on task_type to avoid a GH loop.
"""

import Grasshopper
import scriptcontext as sc

from compas_eve.ghpython import BackgroundWorker
from gh_agent import run_agent, stop_agent

DEFAULT_TASK_TYPE = "fabrication.toolpaths"


class FabricationReceiverComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        task_type: str,
        broker_host: str,
        broker_port: int,
        enabled,
    ):
        broker_host = broker_host or "127.0.0.1"
        broker_port = int(broker_port) if broker_port else 1883
        task_type = task_type or DEFAULT_TASK_TYPE

        # ── Stop ──────────────────────────────────────────────────────────────
        if not enabled:
            BackgroundWorker.stop_instance_by_component(ghenv)  # noqa: F821
            sc.sticky.pop("akt_fab_worker_{}".format(task_type), None)
            ghenv.Component.Message = "disabled"  # noqa: F821
            return None, None, None, None, "disabled"

        # ── Config-change detection ───────────────────────────────────────────
        config = (task_type, broker_host, broker_port)
        config_key = "akt_fab_config_{}".format(ghenv.Component.InstanceGuid)  # noqa: F821
        config_changed = sc.sticky.get(config_key) != config
        sc.sticky[config_key] = config

        # ── BackgroundWorker ──────────────────────────────────────────────────
        worker = BackgroundWorker.instance_by_component(
            ghenv,  # noqa: F821
            lambda w, tt=task_type, bh=broker_host, bp=broker_port: run_agent(
                self, w, tt, bh, bp, "FabricationAgent"
            ),
            dispose_function=stop_agent,
            auto_set_done=False,
            force_new=config_changed,
        )

        # Share worker with the Fabrication Submit component
        sc.sticky["akt_fab_worker_{}".format(task_type)] = worker

        if not worker.is_working() and not worker.is_done():
            worker.start_work()
            ghenv.Component.Message = "starting…"  # noqa: F821
            return None, None, None, None, "starting"

        # ── Expose task data ───────────────────────────────────────────────────
        pending = getattr(worker, "pending_task", None)

        if pending:
            timber_model = pending["inputs"].get("timber_model")
            ghenv.Component.Message = "task received — generate toolpaths!"  # noqa: F821
            return (
                pending["id"],
                timber_model,
                pending["params"],
                pending["output_keys"],
                "task_received",
            )

        ghenv.Component.Message = "listening"  # noqa: F821
        return None, None, None, None, "listening"
