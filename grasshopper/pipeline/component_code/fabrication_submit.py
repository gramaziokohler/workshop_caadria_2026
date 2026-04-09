# r: compas==2.15.1, timber_design==0.2.0, compas_eve
# venv: akt_agent
# env: /Users/chenkasirer/repos/GKR/workshop_caadria_2026/grasshopper/pipeline
"""Fabrication Submit — fabrication_submit.gh

Companion to the Fabrication Receiver component.
Looks up the shared BackgroundWorker via sc.sticky (keyed on task_type),
accepts the computed toolpaths, and sends them back to the orchestrator
when submit is pulsed.

Wire toolpaths from your downstream toolpath generation logic and pulse
submit to approve and release them to the Robot agent.
"""

import Grasshopper
import scriptcontext as sc

from gh_agent import submit_result

DEFAULT_TASK_TYPE = "fabrication.toolpaths"


class FabricationSubmitComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        task_type: str,
        toolpaths,
        submit,
    ):
        task_type = task_type or DEFAULT_TASK_TYPE
        worker = sc.sticky.get("akt_fab_worker_{}".format(task_type))

        if worker is None:
            ghenv.Component.Message = "no receiver"  # noqa: F821
            return "no_receiver"

        pending = getattr(worker, "pending_task", None)

        if submit and toolpaths is not None and pending:
            submit_result(worker, {"toolpaths": toolpaths})
            ghenv.Component.Message = "submitted"  # noqa: F821
            return "submitted"

        if pending:
            ghenv.Component.Message = "waiting for approval"  # noqa: F821
            return "pending"

        ghenv.Component.Message = "idle"  # noqa: F821
        return "idle"
