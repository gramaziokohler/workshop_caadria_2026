# r: compas_timber
"""Lap — creates a Lap processing from explicit parameters.

Inputs
------
orientation : str
    Orientation of the lap: "start" or "end". Default is "start".
start_x : float
    Start X in the reference side parametric space. -100000 < start_x < 100000. Default 0.0.
start_y : float
    Start Y in the reference side parametric space. -50000 < start_y < 50000. Default 0.0.
angle : float
    Horizontal angle of the cut in degrees. 0.1 < angle < 179.9. Default 90.0.
inclination : float
    Vertical angle of the cut in degrees. 0.1 < inclination < 179.9. Default 90.0.
slope : float
    Slope of the cut in degrees. -89.9 < slope < 89.9. Default 0.0.
length : float
    Length of the lap. 0 < length < 100000. Default 200.0.
width : float
    Width of the lap. 0 < width < 50000. Default 50.0.
depth : float
    Depth of the lap. -50000 < depth < 50000. Default 40.0.
lead_angle_parallel : bool
    If True, the lead angle is parallel to the beam axis. Default True.
lead_angle : float
    Lead angle of the cut in degrees. 0.1 < lead_angle < 179.9. Default 90.0.
lead_inclination_parallel : bool
    If True, the lead inclination is parallel to the beam axis. Default True.
lead_inclination : float
    Lead inclination of the cut in degrees. 0.1 < lead_inclination < 179.9. Default 90.0.

Outputs
-------
processing : Lap
    The configured Lap processing object, ready to be added to a beam.
"""

import Grasshopper  # noqa: F401

from compas_timber.fabrication import Lap
from compas_timber.fabrication import OrientationType


class LapComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        orientation: str,
        start_x: float,
        start_y: float,
        angle: float,
        inclination: float,
        slope: float,
        length: float,
        width: float,
        depth: float,
        lead_angle_parallel: bool,
        lead_angle: float,
        lead_inclination_parallel: bool,
        lead_inclination: float,
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
        angle = float(angle) if angle is not None else 90.0
        inclination = float(inclination) if inclination is not None else 90.0
        slope = float(slope) if slope is not None else 0.0
        length = float(length) if length is not None else 200.0
        width = float(width) if width is not None else 50.0
        depth = float(depth) if depth is not None else 40.0
        lead_angle_parallel = bool(lead_angle_parallel) if lead_angle_parallel is not None else True
        lead_angle = float(lead_angle) if lead_angle is not None else 90.0
        lead_inclination_parallel = bool(lead_inclination_parallel) if lead_inclination_parallel is not None else True
        lead_inclination = float(lead_inclination) if lead_inclination is not None else 90.0

        # ── Create processing ─────────────────────────────────────────────────
        processing = Lap(
            orientation=orientation,
            start_x=start_x,
            start_y=start_y,
            angle=angle,
            inclination=inclination,
            slope=slope,
            length=length,
            width=width,
            depth=depth,
            lead_angle_parallel=lead_angle_parallel,
            lead_angle=lead_angle,
            lead_inclination_parallel=lead_inclination_parallel,
            lead_inclination=lead_inclination,
        )

        return processing
