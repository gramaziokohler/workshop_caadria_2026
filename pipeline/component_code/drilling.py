# r: compas_timber
"""Drilling — creates a Drilling processing from explicit parameters.

Inputs
------
start_x : float
    X-coordinate of the drill start in the reference side local coordinate system. -100000 < start_x < 100000. Default 0.0.
start_y : float
    Y-coordinate of the drill start in the reference side local coordinate system. -50000 < start_y < 50000. Default 0.0.
angle : float
    Rotation angle of the drilling around the Z-axis of the reference side, in degrees. 0 < angle < 360. Default 0.0.
inclination : float
    Inclination angle of the drilling around the Y-axis of the reference side, in degrees. 0.1 < inclination < 179.9. Default 90.0.
depth_limited : bool
    If True, drilling depth is limited to `depth`. If False, drilling goes through the element. Default False.
depth : float
    Depth of the drilling in mm (used only when depth_limited is True). Default 50.0.
diameter : float
    Diameter of the drill bit in mm. Default 20.0.

Outputs
-------
processing : Drilling
    The configured Drilling processing object, ready to be added to a beam.
"""

import Grasshopper  # noqa: F401

from compas_timber.fabrication import Drilling


class DrillingComponent(Grasshopper.Kernel.GH_ScriptInstance):
    def RunScript(
        self,
        start_x: float,
        start_y: float,
        angle: float,
        inclination: float,
        depth_limited: bool,
        depth: float,
        diameter: float,
    ):
        # ── Defaults ──────────────────────────────────────────────────────────
        start_x = float(start_x) if start_x is not None else 0.0
        start_y = float(start_y) if start_y is not None else 0.0
        angle = float(angle) if angle is not None else 0.0
        inclination = float(inclination) if inclination is not None else 90.0
        depth_limited = bool(depth_limited) if depth_limited is not None else False
        depth = float(depth) if depth is not None else 50.0
        diameter = float(diameter) if diameter is not None else 20.0

        # ── Create processing ─────────────────────────────────────────────────
        processing = Drilling(
            start_x=start_x,
            start_y=start_y,
            angle=angle,
            inclination=inclination,
            depth_limited=depth_limited,
            depth=depth,
            diameter=diameter,
        )

        return processing
