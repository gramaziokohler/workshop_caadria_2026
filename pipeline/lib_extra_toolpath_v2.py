"""Generate milling toolpaths for Lap processings directly from BTLx parameters.

Uses the parametric BTLx description of a Lap (start_x, start_y, angle,
inclination, length, width, depth) to derive the pocket coordinate system and
raster a flat-end mill through it.

The BTLx parameters define a local coordinate system on the beam's reference
side.  ``start_x`` / ``start_y`` locate the pocket origin via the ref-side
surface, and ``angle`` / ``inclination`` / ``slope`` orient that frame.  The
pocket then extends ``length`` along the frame's -normal, ``width`` along its
yaxis, and ``depth`` into the beam (perpendicular to the ref side).  A
machining strategy (zig-zag raster, depth layers) is applied in that space.

Usage
-----
    frames = lap_toolpath(
        beam,
        lap_processing,
        bit_diameter=12.0,   # mm
        num_passes=3,        # depth layers
        path_step=2.0,       # mm between frames along a pass (optional)
    )
"""

import math

from compas.geometry import Frame
from compas.geometry import Point
from compas.geometry import Vector
from compas.itertools import linspace
from compas_timber.elements import Beam
from compas_timber.fabrication import Lap
from compas_timber.fabrication import LapProxy

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def lap_toolpath(
    beam,
    processing,
    bit_diameter,
    num_passes=1,
    path_step=None,
    stepover=None,
    approach_height=5.0,
):
    """Create an ordered list of tool-tip frames for milling a Lap pocket.

    The pocket coordinate system is derived directly from the BTLx parameters:

    * **origin** – ``start_x`` / ``start_y`` mapped onto the ref-side surface.
    * **length direction** – ``-start_frame.normal`` (determined by ``angle`` /
      ``inclination`` / ``slope``).
    * **width direction** – ``start_frame.yaxis``.
    * **depth direction** – into the beam, perpendicular to the reference side.

    ``length``, ``width`` and ``depth`` are used as-is for the pocket extents.

    Parameters
    ----------
    beam : :class:`compas_timber.elements.Beam`
        The beam on which the lap is applied.
    processing : :class:`Lap` | :class:`LapProxy`
        The lap processing whose BTLx parameters drive the toolpath.
    bit_diameter : float
        Diameter of the flat-end milling bit (same units as the model).
    num_passes : int, optional
        Number of depth passes to reach the full pocket depth.  Default is 1.
    path_step : float, optional
        Distance between successive frames along a single raster line.
        If ``None``, defaults to ``bit_diameter / 2``.
    stepover : float, optional
        Lateral distance between adjacent raster lines (center-to-center).
        If ``None``, defaults to ``bit_diameter * 0.6`` (40 % overlap).
    approach_height : float, optional
        Safe height above the pocket top for approach / retract moves.
        Default is ``5.0``.

    Returns
    -------
    list[:class:`compas.geometry.Frame`]
        Ordered tool-tip frames.  The Z-axis of each frame points *into*
        the material (tool / spindle axis).
    """
    if isinstance(processing, LapProxy):
        processing = processing.unproxified()

    bit_radius = bit_diameter / 2.0
    if path_step is None:
        path_step = bit_diameter / 2.0
    if stepover is None:
        stepover = bit_diameter * 0.6

    # ------------------------------------------------------------------
    # 1.  Pocket coordinate system – straight from BTLx parameters
    # ------------------------------------------------------------------
    #     _start_frame_from_params_and_beam converts (start_x, start_y,
    #     angle, inclination, slope) into a 3-D frame on the ref side.
    start_frame = processing._start_frame_from_params_and_beam(beam)
    ref_frame = beam.ref_sides[processing.ref_side_index]

    # Length direction: pocket extends from the start wall toward the end
    # wall, which sits at  start_frame.point - start_frame.normal * length.
    length_dir = Vector(*(-start_frame.normal))

    # Width direction: lateral extent of the pocket on the ref-side surface.
    width_dir = Vector(*start_frame.yaxis)

    # Depth direction: into the beam, perpendicular to the reference side.
    depth_dir = Vector(*(-ref_frame.normal))

    # BTLx dimensions – used directly, no geometric reconstruction.
    length = processing.length
    width = processing.width
    depth = processing.depth

    # ------------------------------------------------------------------
    # 2.  Tool-frame orientation (Z into material)
    # ------------------------------------------------------------------
    #     Build a right-handed frame whose Z-axis equals depth_dir.
    tool_x = Vector(*length_dir)
    tool_y = Vector(*depth_dir.cross(length_dir))
    tool_y.unitize()
    # tool_z = tool_x × tool_y   →   by construction this equals depth_dir

    # ------------------------------------------------------------------
    # 3.  Raster layout
    # ------------------------------------------------------------------
    usable_length = length - 2.0 * bit_radius
    usable_width = width - 2.0 * bit_radius

    if usable_length <= 0 or usable_width <= 0:
        raise ValueError("Bit diameter ({:.2f}) is too large for this pocket (length={:.2f}, width={:.2f}).".format(bit_diameter, length, width))

    # Raster lines across the width
    num_lines = max(1, int(math.ceil(usable_width / stepover)) + 1)
    actual_stepover = usable_width / max(num_lines - 1, 1)

    # Points per raster line
    num_points = max(2, int(math.ceil(usable_length / path_step)) + 1)

    # Pocket origin offset inward by bit_radius from the start & front walls
    origin = Point(*start_frame.point) + length_dir * bit_radius + width_dir * bit_radius

    pass_depth = depth / num_passes

    # ------------------------------------------------------------------
    # 4.  Generate frames
    # ------------------------------------------------------------------
    frames = []

    # ---- safe approach above the pocket ----
    approach_pt = origin - depth_dir * approach_height
    frames.append(Frame(approach_pt, tool_x, tool_y))

    for pass_idx in range(num_passes):
        d_offset = depth_dir * (pass_depth * (pass_idx + 1))

        for line_idx in range(num_lines):
            w_offset = width_dir * (actual_stepover * line_idx)

            # zig-zag: alternate length direction each line
            t_values = list(linspace(0.0, 1.0, num_points))
            if line_idx % 2 == 1:
                t_values = list(reversed(t_values))

            for t in t_values:
                pt = origin + length_dir * (usable_length * t) + w_offset + d_offset
                frames.append(Frame(pt, tool_x, tool_y))

    # ---- safe retract above the last point ----
    retract_pt = Point(*frames[-1].point) - depth_dir * approach_height
    frames.append(Frame(retract_pt, tool_x, tool_y))

    return frames


# ---------------------------------------------------------------------------
# Convenience helper
# ---------------------------------------------------------------------------


def lap_toolpaths_for_beam(
    beam,
    bit_diameter,
    num_passes=1,
    path_step=None,
    stepover=None,
    approach_height=5.0,
):
    """Generate toolpath frames for every Lap processing on *beam*.

    Returns
    -------
    list[tuple[Lap, list[Frame]]]
        A list of ``(processing, frames)`` pairs.
    """
    results = []
    for processing in beam.processings:
        if isinstance(processing, (Lap, LapProxy)):
            frames = lap_toolpath(
                beam,
                processing,
                bit_diameter=bit_diameter,
                num_passes=num_passes,
                path_step=path_step,
                stepover=stepover,
                approach_height=approach_height,
            )
            results.append((processing, frames))
    return results


# ---------------------------------------------------------------------------
# Quick demo / self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from compas.geometry import Line

    centerline = Line(Point(0, 0, 0), Point(1000, 0, 0))
    beam = Beam.from_centerline(centerline, width=100, height=200)

    lap = Lap(
        orientation="start",
        start_x=100.0,
        start_y=0.0,
        angle=90.0,
        inclination=90.0,
        slope=0.0,
        length=200.0,
        width=100.0,
        depth=50.0,
        lead_angle=90.0,
        lead_angle_parallel=True,
        lead_inclination=90.0,
        lead_inclination_parallel=True,
        ref_side_index=0,
    )

    frames = lap_toolpath(
        beam,
        lap,
        bit_diameter=12.0,
        num_passes=3,
        path_step=2.0,
    )
    print("Generated {} toolpath frames".format(len(frames)))
    print("First frame: {}".format(frames[0]))
    print("Last frame:  {}".format(frames[-1]))
