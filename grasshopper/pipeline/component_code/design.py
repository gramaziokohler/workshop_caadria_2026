# r: compas==2.15.1, timber_design==0.2.0, compas_eve
# venv: akt_agent
# env: /Users/chenkasirer/repos/GKR/workshop_caadria_2026/grasshopper/pipeline

"""Design Agent — design.gh

Listens for a 'design.compute' task from the orchestrator.
When a task arrives the component re-solves and exposes any orchestrator
params on the `params` output.  Wire your TimberModel into `timber_model`
and pulse `submit` when you are happy with the design.

The agent sends the model back to the orchestrator which stores it in the
session and forwards it to the Fabrication agent.
"""

import Grasshopper
import scriptcontext as sc

from compas_eve.ghpython import BackgroundWorker
from gh_agent import run_agent, stop_agent, submit_result

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
            return None, None, None, "disabled"

        # ── Config-change detection → force fresh worker ──────────────────────
        config = (task_type, broker_host, broker_port)
        config_key = "akt_design_config_{}".format(ghenv.Component.InstanceGuid)  # noqa: F821
        config_changed = sc.sticky.get(config_key) != config
        sc.sticky[config_key] = config

        # ── BackgroundWorker ──────────────────────────────────────────────────
        worker = BackgroundWorker.instance_by_component(
            ghenv,  # noqa: F821
            lambda w, tt=task_type, bh=broker_host, bp=broker_port: run_agent(
                self, w, tt, bh, bp, "DesignAgent"
            ),
            dispose_function=stop_agent,
            auto_set_done=False,
            force_new=config_changed,
        )

        if not worker.is_working() and not worker.is_done():
            worker.start_work()
            ghenv.Component.Message = "starting…"  # noqa: F821
            return None, None, None, "starting"

        # ── Submit ────────────────────────────────────────────────────────────
        pending = getattr(worker, "pending_task", None)

        if submit and timber_model is not None and pending:
            submit_result(worker, {"timber_model": timber_model})
            ghenv.Component.Message = "listening"  # noqa: F821
            return None, None, None, "submitted"

        # ── Expose current task to the canvas ─────────────────────────────────
        if pending:
            ghenv.Component.Message = "task received — design!"  # noqa: F821
            return (
                pending["id"],
                pending["params"],
                pending["output_keys"],
                "task_received",
            )

        ghenv.Component.Message = "listening"  # noqa: F821
        return None, None, None, "listening"
