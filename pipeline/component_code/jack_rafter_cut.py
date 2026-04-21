# r: compas_timber
"""Jack Rafter Cut — creates a JackRafterCut processing from explicit parameters.

Inputs
------
orientation : str
    Orientation of the cut: "start" or "end". Default is "start".
start_x : float
    Start X in the reference side parametric space. -100000 < start_x < 100000. Default 0.0.
start_y : float
    Start Y in the reference side parametric space. 0 < start_y < 50000. Default 0.0.
start_depth : float
    Depth of the cut start. 0 < start_depth < 50000. Default 0.0.
angle : float
    Horizontal angle of the cut in degrees. 0.1 < angle < 179.9. Default 90.0.
inclination : float
    Vertical angle of the cut in degrees. 0.1 < inclination < 179.9. Default 90.0.

Outputs
-------
processing : JackRafterCut
    The configured JackRafterCut processing object, ready to be added to a beam.
"""

import Grasshopper  # noqa: F401

from compas_rhino.devtools import DevTools

DevTools.ensure_path()

from compas_timber.fabrication import JackRafterCut
from compas_timber.fabrication import OrientationType


class JackRafterCutComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        orientation: str,
        start_x: float,
        start_y: float,
        start_depth: float,
        angle: float,
        inclination: float,
    ):
        # ── Defaults ──────────────────────────────────────────────────────────
        if orientation is None:
            orientation = OrientationType.START
        else:
            orientation = orientation.strip().lower()
            if orientation not in (OrientationType.START, OrientationType.END):
                self.AddRuntimeMessage(
                    Grasshopper.Kernel.GH_RuntimeMessageLevel.Error,
                    "orientation must be 'start' or 'end'.",
                )
                return None

        start_x = float(start_x) if start_x is not None else 0.0
        start_y = float(start_y) if start_y is not None else 0.0
        start_depth = float(start_depth) if start_depth is not None else 0.0
        angle = float(angle) if angle is not None else 90.0
        inclination = float(inclination) if inclination is not None else 90.0

        # ── Create processing ─────────────────────────────────────────────────
        processing = JackRafterCut(
            orientation=orientation,
            start_x=start_x,
            start_y=start_y,
            start_depth=start_depth,
            angle=angle,
            inclination=inclination,
        )

        return processing
