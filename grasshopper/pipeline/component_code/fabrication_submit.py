# r: compas==2.15.1, timber_design==0.2.0, compas_eve
# venv: akt_agent

"""Fabrication Submit — fabrication_submit.gh

Companion to the Fabrication Receiver component.
Looks up the shared BackgroundWorker via sc.sticky (keyed on task_type),
accepts the computed toolpaths, and sends them back to the orchestrator
when submit is pulsed.

Wire toolpaths from your downstream toolpath generation logic and pulse
submit to approve and release them to the Robot agent.
"""

import Grasshopper

from compas_rhino.conversions import plane_to_compas_frame


DEFAULT_TASK_TYPE = "fabrication.toolpaths"


class FabricationSubmitComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(self, pending_task, timber_model, toolpaths: list[object], submit):
        print("ran!")
        print(getattr(pending_task, "event", None))
        if pending_task is None:
            ghenv.Component.Message = "no receiver"  # noqa: F821
            return "no_receiver"
        if submit and pending_task:
            compas_toolpaths = [plane_to_compas_frame(path) for path in toolpaths]
            pending_task.task_outputs = {
                "toolpaths": compas_toolpaths,
                "timber_model": timber_model,
            }
            if pending_task.event:
                print("setting event!")
                pending_task.event.set()

            ghenv.Component.Message = "submitted"  # noqa: F821
            return "submitted"

        if pending_task:
            ghenv.Component.Message = "waiting for approval"  # noqa: F821
            return "pending"

        ghenv.Component.Message = "idle"  # noqa: F821
        return "idle"
