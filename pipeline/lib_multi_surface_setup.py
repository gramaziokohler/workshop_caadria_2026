
import Rhino.Geometry as rg  # type: ignore

from compas.datastructures import Mesh
from compas.geometry import NurbsSurface
from compas.geometry import Point, Vector, Line, Frame
from compas.geometry import closest_point_on_line, closest_point_on_polyline, distance_point_line, intersection_line_line
from compas_rhino.conversions import polyline_to_compas

from compas_timber.connections import LMiterJoint, TButtJoint, XLapJoint
from compas_timber.elements import Beam
from compas_timber.model import TimberModel


# ----- MULTI FACE QUAD MESHER ---- #
class MultiQuadMesher:
    """
    Class to generate a quad mesh over a Rhino Brep with multiple faces,
    it can ensure connectivvity along shared edges if the the shared edge is not trimmed.

    Parameters
    ----------
    u_count : int
        Number of divisions in the U direction per face.
    v_count : int
        Number of divisions in the V direction per face.
    brep : rg.Brep
        The Rhino Brep to mesh.
    full_quads : bool, optional
        If True, only full quads that lie entirely on the Brep face are created.
        If False, all quads are created regardless of whether they lie fully on the face.
        Default is False.

    Attributes
    ----------
    mesh : Mesh
        The generated quad mesh.
    brep_vertex_to_mesh_key : dict
        Mapping from Brep vertex indices to mesh vertex keys.
    edge_param_to_mesh_key : dict
        Mapping from (edge_index, normalized_t) to mesh vertex keys for edge vertices.
    face_vertex_grid : dict
        Mapping from (face_index, u_index, v_index) to mesh vertex keys.
    vertex_to_faces : dict
        Mapping from mesh vertex keys to sets of face indices they belong to.
    faces : list[rg.BrepFace]
        List of Brep faces.
    surfaces : list[NurbsSurface]
        List of Nurbs surfaces corresponding to the Brep faces.
    vertices : list[Point]
        List of Brep vertices as COMPAS Points.
    """

    def __init__(self, u_count: int, v_count: int, brep: rg.Brep, full_quads: bool = False):
        self.u_count = u_count
        self.v_count = v_count
        self.brep = brep
        self.full_quads = full_quads
        self.mesh = Mesh()

        # Topology maps for ensuring connectivity
        self.brep_vertex_to_mesh_key = {}  # brep vertex index -> mesh vertex key
        self.edge_param_to_mesh_key = {}  # (edge_index, normalized_t) -> mesh vertex key
        self.face_vertex_grid = {}  # (face_index, u_index, v_index) -> mesh vertex key
        self.vertex_to_faces = {}  # mesh vertex key -> set of face indices

    @property
    def faces(self) -> list[rg.BrepFace]:
        """Return the Brep faces."""
        return self.brep.Faces

    @property
    def surfaces(self) -> list[NurbsSurface]:
        """Return the NurbsSurface of each Brep face."""
        return [NurbsSurface.from_native(face.UnderlyingSurface()) for face in self.faces]

    @property
    def vertices(self) -> list[Point]:
        """Return the Brep vertices as COMPAS points."""
        vertices = [v.Location for v in self.brep.Vertices]
        return [Point(v.X, v.Y, v.Z) for v in vertices]


    def is_point_on_face(self, point, face_idx: int) -> bool:
        """Check if a point is on a specific face."""
        face = self.brep.Faces[face_idx]
        success, face_u, face_v = face.ClosestPoint(
            rg.Point3d(point.x, point.y, point.z)
        )
        if not success:
            return False
        relation = face.IsPointOnFace(face_u, face_v)
        if relation == rg.PointFaceRelation.Interior:
            return True
        if relation == rg.PointFaceRelation.Boundary:
            return True
        return False

    def _initialize_brep_vertex_map(self) -> None:
        """Create mesh vertices for all Brep vertices."""
        for brep_v_idx in range(self.brep.Vertices.Count):
            brep_v = self.brep.Vertices[brep_v_idx]
            pt = brep_v.Location
            key = self.mesh.add_vertex(x=pt.X, y=pt.Y, z=pt.Z)
            self.brep_vertex_to_mesh_key[brep_v_idx] = key
            # Initialize tracking for this vertex
            self.vertex_to_faces[key] = set()

    def _get_edge_vertex_key(self, edge_idx: int, t_param: float, point: rg.Point3d) -> int:
        """Get or create mesh vertex key for a point on a Brep edge."""
        # Normalize parameter to 0-1 range
        edge = self.brep.Edges[edge_idx]
        domain = edge.Domain
        t_normalized = (t_param - domain.Min) / (domain.Max - domain.Min)

        # Round to match our grid divisions
        tolerance = 1e-6

        # Check if it's at edge start or end vertex
        if abs(t_normalized) < tolerance:
            # Start vertex
            return self.brep_vertex_to_mesh_key[edge.StartVertex.VertexIndex]
        elif abs(t_normalized - 1.0) < tolerance:
            # End vertex
            return self.brep_vertex_to_mesh_key[edge.EndVertex.VertexIndex]

        # Round t_normalized to nearest grid point
        for div in range(1, max(self.u_count, self.v_count)):
            grid_t = div / max(self.u_count, self.v_count)
            if abs(t_normalized - grid_t) < tolerance:
                t_normalized = grid_t
                break

        # Create key for edge parameter
        key_tuple = (edge_idx, round(t_normalized, 6))

        if key_tuple in self.edge_param_to_mesh_key:
            return self.edge_param_to_mesh_key[key_tuple]
        else:
            # Create new vertex
            mesh_key = self.mesh.add_vertex(x=point.X, y=point.Y, z=point.Z)
            self.edge_param_to_mesh_key[key_tuple] = mesh_key
            # Initialize tracking for this vertex
            if mesh_key not in self.vertex_to_faces:
                self.vertex_to_faces[mesh_key] = set()
            return mesh_key

    def _get_face_boundary_edge_and_param(self, face_idx: int, u_normalized: float, v_normalized: float):
        """
        Check if UV position is on a face boundary edge.
        Returns (edge_index, t_parameter) or None if interior.
        """
        tolerance = 1e-6
        face = self.faces[face_idx]

        # Determine which boundary we're on
        on_u_min = abs(u_normalized) < tolerance
        on_u_max = abs(u_normalized - 1.0) < tolerance
        on_v_min = abs(v_normalized) < tolerance
        on_v_max = abs(v_normalized - 1.0) < tolerance

        if not (on_u_min or on_u_max or on_v_min or on_v_max):
            return None  # Interior point

        # Get actual UV coordinates
        surface = self.surfaces[face_idx]
        u = surface.domain_u[0] + u_normalized * (surface.domain_u[1] - surface.domain_u[0])
        v = surface.domain_v[0] + v_normalized * (surface.domain_v[1] - surface.domain_v[0])

        point_3d = rg.Point3d(surface.point_at(u, v).x, surface.point_at(u, v).y, surface.point_at(u, v).z)

        # Find which Brep edge this corresponds to
        min_distance = float('inf')
        closest_edge_idx = None
        closest_t = None

        for loop in face.Loops:
            for trim in loop.Trims:
                edge = trim.Edge
                if edge is None:
                    continue

                edge_idx = edge.EdgeIndex
                success, t = edge.ClosestPoint(point_3d)
                if not success:
                    continue
                pt_on_edge = edge.PointAt(t)
                distance = point_3d.DistanceTo(pt_on_edge)

                if distance < min_distance and distance < 0.01:  # tolerance
                    min_distance = distance
                    closest_edge_idx = edge_idx
                    closest_t = t

        if closest_edge_idx is not None:
            return (closest_edge_idx, closest_t)

        return None

    def _generate_vertices(self) -> None:
        """Generate vertices for all faces, ensuring shared edges use same vertices."""
        # First, create vertices for all Brep vertices
        self._initialize_brep_vertex_map()

        # Generate vertices for each face
        for fi, face in enumerate(self.faces):
            surface = self.surfaces[fi]

            for ui in range(self.u_count + 1):
                for vi in range(self.v_count + 1):
                    # Normalized UV coordinates (0 to 1)
                    u_normalized = ui / self.u_count
                    v_normalized = vi / self.v_count

                    # Actual UV coordinates in surface domain
                    u = surface.domain_u[0] + u_normalized * (surface.domain_u[1] - surface.domain_u[0])
                    v = surface.domain_v[0] + v_normalized * (surface.domain_v[1] - surface.domain_v[0])

                    point = surface.point_at(u, v)
                    point_3d = rg.Point3d(point.x, point.y, point.z)

                    # Check if this point is on a boundary edge
                    edge_info = self._get_face_boundary_edge_and_param(fi, u_normalized, v_normalized)

                    if edge_info is not None:
                        # Point is on a Brep edge - use shared vertex
                        edge_idx, t_param = edge_info
                        key = self._get_edge_vertex_key(edge_idx, t_param, point_3d)
                    else:
                        # Interior point - create new vertex
                        key = self.mesh.add_vertex(x=point.x, y=point.y, z=point.z)

                    # Store in grid mapping
                    self.face_vertex_grid[(fi, ui, vi)] = key

                    # Track which faces this vertex belongs to
                    if key not in self.vertex_to_faces:
                        self.vertex_to_faces[key] = set()
                    self.vertex_to_faces[key].add(fi)


    def generate_mesh(self) -> Mesh:
        """
        Generate the quad mesh over the Brep.

        Returns
        -------
        Mesh
            The generated quad mesh.
        """
        self._generate_vertices()

        # Generate faces for each Brep face
        for fi in range(self.faces.Count):
            for ui in range(self.u_count):
                for vi in range(self.v_count):
                    # Get vertex keys from grid mapping
                    v1 = self.face_vertex_grid[(fi, ui, vi)]
                    v2 = self.face_vertex_grid[(fi, ui + 1, vi)]
                    v3 = self.face_vertex_grid[(fi, ui + 1, vi + 1)]
                    v4 = self.face_vertex_grid[(fi, ui, vi + 1)]

                    if self.full_quads:
                        p1 = self.mesh.vertex_point(v1)
                        p2 = self.mesh.vertex_point(v2)
                        p3 = self.mesh.vertex_point(v3)
                        p4 = self.mesh.vertex_point(v4)


                        if all([self.is_point_on_face(pt, fi) for pt in [p1, p2, p3, p4]]):
                            self.mesh.add_face([v1, v2, v3, v4])
                    else:
                        self.mesh.add_face([v1, v2, v3, v4])

        return self.mesh

# ----- MULTI FACE RF SYSTEM ---- #
class MultiFaceRFSystem:
    """
    A class representing a multi-face reciprocal frame (RF) system.
    It provides methods to create the RF system data structure,
    relax the mesh, adjust centerlines, and compute a timber model.

    Parameters
    ----------
    mesher : MultiFaceQuadMesher
        An instance of MultiFaceQuadMesher containing the mesh and Brep.

    Attributes
    ----------
    mesh : Mesh
        The mesh representing the RF system.
    brep : Rhino.Geometry.Brep
        The Brep geometry associated with the RF system.
    mesher : MultiFaceQuadMesher
        The mesher used to generate the mesh and Brep.
    ceterlines : list[Line]
        A list of centerlines for each edge in the RF system. The centerlines are used to define the beams of the TimberModel.

    """
    def __init__(self, mesher):
        self.mesh = mesher.mesh
        self.brep = mesher.brep
        self.mesher = mesher

    @property
    def centerlines(self) -> list:
        lines = [self.mesh.edge_attribute(edge, "centerline") for edge in self.mesh.edges()]
        return lines


    def copy(self) -> "MultiFaceRFSystem":
        """
        Create a copy of the MultiFaceRFSystem instance.

        Returns
        -------
        MultiFaceRFSystem
            A new instance of MultiFaceRFSystem with a copy of the mesh.
        """
        new_rf_system = MultiFaceRFSystem(
            mesher = self.mesher
        )
        new_rf_system.mesh = self.mesh.copy()
        return new_rf_system


    #---- MESH RELAXATION ---- #

    def relax_mesh(self,
                   iterations=50,
                   damping=0.2,
                   modifiers=None,
                   snap_to_surface=True,
                   attract_to_brep_vertices=True,
                   ignore_interior_vertices=True,
                   snap_on_brep_edges=False) -> Mesh:
        """
        Relax the mesh using the MultiSurfaceMeshRelax class.

        Parameters
        ----------
        iterations : int, optional
            Number of relaxation iterations. Default is 50.
        damping : float, optional
            Damping factor for the relaxation. Default is 0.2.
        modifiers : list, optional
            List of modifier functions to apply during relaxation. Default is None.
        snap_to_surface : bool, optional
            Whether to snap vertices to the Brep surface. Default is True.
        attract_to_brep_vertices : bool, optional
            Whether to attract vertices to Brep vertices. Default is True.
        ignore_interior_vertices : bool, optional
            Whether to ignore interior vertices during relaxation. Default is True.
        snap_on_brep_edges : bool, optional
            Whether to snap vertices on Brep edges. Default is False.
        Returns
        -------
        Mesh
            The relaxed mesh.
        """
        relaxer = MultiSurfaceMeshRelax(
            mesh = self.mesh,
            brep = self.brep,
            iterations=iterations,
            damping=damping,
            snap_to_surface=snap_to_surface,
            attract_to_brep_vertices=attract_to_brep_vertices,
            ignore_interior_vertices=ignore_interior_vertices,
            snap_on_brep_edges=snap_on_brep_edges
        )
        if modifiers:
            for mod in modifiers:
                relaxer.add_modifier(mod)
        self.mesh = relaxer.relax()
        return self.mesh


    # ---- RF SYSTEM DATASTRUCTURE ---- #

    def set_targets_as_attributes(self) -> None:
        """
        For each vertex in the mesh, sets the attributes "on_brep_edge" and "target_contour".
        """
        for vertex in self.mesh.vertices():
            face_index_set = self.mesher.vertex_to_faces[vertex]
            if len(face_index_set) == 0:
                continue  # skip vertices shared by multiple faces
            elif len(face_index_set) > 1:
                self.mesh.vertex_attribute(vertex, "on_brep_edge", True)
            else:
                self.mesh.vertex_attribute(vertex, "on_brep_edge", False)

            face = self.mesher.faces[list(face_index_set)[0]]
            # set the the target contour
            brep_loop = face.OuterLoop
            curve = brep_loop.To3dCurve()
            curve = curve.ToPolyline(1, 1, 0, 0)
            curve = curve.TryGetPolyline()[1]
            polyline_countour = polyline_to_compas(curve)
            self.mesh.vertex_attribute(vertex, "target_contour", polyline_countour)


    def create_rf_datastructure(self) -> None:
        self._create_rf_datastructure()
        return None

    def _create_rf_datastructure(self) -> None:
        """
        For each edge on the mesh adds the attrivutes "next_edge" and "prev_edge" relative
        to the RF system. It also adds the "centerline" attribute to each edge.
        """
        for edge in self.mesh.edges():
            # set a centerline as attribute
            line = self.mesh.edge_line(edge)
            self.mesh.edge_attribute(edge, "centerline", line)
            # next and previous edges are not defined for boundary edges
            if self.mesh.is_edge_on_boundary(edge):
                continue
            # set next and previous edges attributes
            next_edge = self._compute_next_rf_edge(edge)
            prev_edge = self._compute_prev_rf_edge(edge)
            self.mesh.edge_attribute(edge, "next_edge", next_edge)
            self.mesh.edge_attribute(edge, "prev_edge", prev_edge)
            # sets the edge normal attribute
            edge_normal = self._compute_edge_normal(edge)
            self.mesh.edge_attribute(edge, "normal", edge_normal)
        return None

    def _compute_next_rf_edge(self, edge):
        """ Given an edge, computes the next edge in the RF system."""
        face = self.mesh.halfedge_face(edge)
        next_halffedge_index = (self.mesh.face_halfedges(face).index(edge) + 1) % len(self.mesh.face_halfedges(face))
        next_halfedge = self.mesh.face_halfedges(face)[next_halffedge_index]
        return next_halfedge

    def _compute_prev_rf_edge(self, edge):
        """ Given an edge, computes the previous edge in the RF system."""
        edge = (edge[1], edge[0])
        previous_halfedge = self._compute_next_rf_edge(edge)
        return previous_halfedge

    def _compute_edge_normal(self, edge) -> Vector:
        """ Given an edge, computes the normal vector as the average of the normals of the two adjacent faces."""
        faces = self.mesh.edge_faces(edge)
        normal_1 = self.mesh.face_normal(faces[0])
        normal_2 = self.mesh.face_normal(faces[1])
        edge_normal = normal_1 + normal_2
        edge_normal.unitize()
        return edge_normal

    def solve_mesh_topology(self) -> Mesh:
        """
        Iteratively resolves the mesh topology by adding vertices to edges
        where necessary, ensuring no infinite loops occurs.
        Returns
        -------
        Mesh
            The updated mesh with resolved topology.
        """
        for _ in range(100):
            edge, vertex = self._find_a_vertex_on_an_edge()
            if not edge or not vertex:
                break  # Exit the loop when no more vertices are found on edges
            self._add_vertex_to_face(edge, vertex)
        self._rebuild_mesh()
        return self.mesh

    def _find_a_vertex_on_an_edge(self):
        """ Finds a vertex that lies on an edge of the mesh but is not part of that edge.
        Returns
        -------
        edge : tuple
            The edge where a vertex is found.
        vertex : int
            The vertex that lies on the edge.
        """
        for face in self.mesh.faces():
            if not self.mesh.is_face_on_boundary(face):
                continue
            for edge in self.mesh.face_halfedges(face):
                if not self.mesh.is_edge_on_boundary(edge):
                    continue
                # check if the edge has a vertex on it
                for vertex in list(self.mesh.vertices()):
                    if vertex in edge:
                        continue
                    edge_line = self.mesh.edge_line(edge)
                    if not edge_line:
                        continue
                    vertex_point = self.mesh.vertex_point(vertex)
                    if vertex_point.on_segment(edge_line):
                        return edge, vertex
        return None, None

    def _add_vertex_to_face(self, edge, vertex) -> bool:
        """
        Adds a vetex to a face by splitting the face along the edge.

        Parameters
        ----------
        edge : tuple
            The edge where the vertex will be added.
        vertex : int
            The vertex to be added to the face.
        """
        print("Adding vertex", vertex, "to edge", edge)
        face = self.mesh.edge_faces(edge)
        face = face[0] if face[0] else face[1]
        vertices = self.mesh.face_vertices(face)
        print(vertices)
        start_index = vertices.index(edge[0])
        print(start_index)
        vertices.insert(start_index + 1, vertex)
        print(vertices)
        print(face)
        self.mesh.add_face(vertices)
        self.mesh.delete_face(face)


    def _rebuild_mesh(self) -> Mesh:
        """
        Rebuilds the mesh to remove any unused vertices after topology changes.

        Returns
        -------
        Mesh
            The rebuilt mesh with unused vertices removed.
        """
        new_mesh = Mesh()
        for vertex in self.mesh.vertices():
            point = self.mesh.vertex_point(vertex)
            new_mesh.add_vertex(x=point.x, y=point.y, z=point.z)
        for face in self.mesh.faces():
            vertices = self.mesh.face_vertices(face)
            new_mesh.add_face(vertices)
        self.mesh = None
        self.mesh = new_mesh
        self.mesh.remove_unused_vertices()
        return self.mesh



    # ---- RF SYSTEM CENTERLINES ROTATION ---- #

    def eccentrize_centerlines(self, eccentricity: float) -> Mesh:
        """
        Moves the centerlines of the RF system edges according to the eccentricity value.

        Parameters
        ----------
        eccentricity : float
            The amount by which to move the centerlines.

        Returns
        -------
        Mesh
            The updated mesh with eccentrized centerlines.
        """
        for edge in self.mesh.edges():
            if self.mesh.is_edge_on_boundary(edge):
                continue
            next_edge = self.mesh.edge_attribute(edge, "next_edge")
            prev_edge = self.mesh.edge_attribute(edge, "prev_edge")
            centerline = self.mesh.edge_attribute(edge, "centerline")

            next_edge_direction = self.mesh.edge_direction(next_edge).unitized()
            prev_edge_direction = self.mesh.edge_direction(prev_edge).unitized()

            start_displacement = prev_edge_direction * eccentricity
            end_displacement = -start_displacement + next_edge_direction * eccentricity

            centerline.start += start_displacement
            centerline.end += end_displacement
            self.mesh.edge_attribute(edge, "centerline", centerline)
        return self.mesh

    def eccentrize_centerlines_attractor_point(self, point: Point, factor: float) -> Mesh:
        """
        Applies eccentricity to centerlines based on distance to an attractor point.
        The amount of movement is determined by the distance to the point.

        Parameters
        ----------
        point : Point
            The attractor point.
        factor : float
            The factor to scale the eccentricity based on distance.

        Returns
        -------
        Mesh
            The updated mesh with eccentrized centerlines.
        """
        for edge in self.mesh.edges():
            if self.mesh.is_edge_on_boundary(edge):
                continue
            next_edge = self.mesh.edge_attribute(edge, "next_edge")
            prev_edge = self.mesh.edge_attribute(edge, "prev_edge")
            centerline = self.mesh.edge_attribute(edge, "centerline")

            next_edge_direction = self.mesh.edge_direction(next_edge).unitized()
            prev_edge_direction = self.mesh.edge_direction(prev_edge).unitized()

            node_0 = self.mesh.vertex_point(edge[0])
            node_1 = self.mesh.vertex_point(edge[1])
            eccentricity_0 = point.distance_to_point(node_0) * factor
            eccentricity_1 = point.distance_to_point(node_1) * factor

            start_displacement = prev_edge_direction * eccentricity_0
            end_displacement = -start_displacement + next_edge_direction * eccentricity_1

            centerline.start += start_displacement
            centerline.end += end_displacement
            self.mesh.edge_attribute(edge, "centerline", centerline)
        return self.mesh

    def eccentrize_centerlines_attractor_curve(self, curve, factor: float) -> Mesh:
        """
        Applies eccentricity to centerlines based on distance to an attractor curve.
        The amount of movement is determined by the distance to the curve.

        Parameters
        ----------
        curve : Polyline
            The attractor curve.
        factor : float
            The factor to scale the eccentricity based on distance.
        """
        for edge in self.mesh.edges():
            if self.mesh.is_edge_on_boundary(edge):
                continue
            next_edge = self.mesh.edge_attribute(edge, "next_edge")
            prev_edge = self.mesh.edge_attribute(edge, "prev_edge")
            centerline = self.mesh.edge_attribute(edge, "centerline")

            next_edge_direction = self.mesh.edge_direction(next_edge).unitized()
            prev_edge_direction = self.mesh.edge_direction(prev_edge).unitized()

            node_0 = self.mesh.vertex_point(edge[0])
            node_1 = self.mesh.vertex_point(edge[1])
            closest_point_0 = curve.closest_point(node_0)
            closest_point_1 = curve.closest_point(node_1)
            eccentricity_0 = closest_point_0.distance_to_point(node_0) * factor
            eccentricity_1 = closest_point_1.distance_to_point(node_1) * factor

            start_displacement = prev_edge_direction * eccentricity_0
            end_displacement = -start_displacement + next_edge_direction * eccentricity_1

            centerline.start += start_displacement
            centerline.end += end_displacement
            self.mesh.edge_attribute(edge, "centerline", centerline)

            print("Hello from the loops@!")
        return self.mesh

    def adjust_centerlines(self, iterations = 50, damping = 0.1) -> None:
        """
        Adjust the centerlines of the RF system edges by applying a spring system simulation.

        Parameters
        ----------
        iterations : int, optional
            Number of adjustment iterations. Default is 50.
        damping : float, optional
            Damping factor for the adjustment. Default is 0.1.
        """
        for _ in range(iterations):
            self._compute_spring_forces(damping)
            self._apply_spring_forces()
        return None

    def _compute_spring_forces(self, damping):
        """
        Computes the spring forces for each edge in the RF system.

        Parameters
        ----------
        damping : float
            Damping factor for the spring forces.
        """
        for edge in self.mesh.edges():
            if self.mesh.is_edge_on_boundary(edge):
                continue
            # get the data of the edge
            centerline = self.mesh.edge_attribute(edge, "centerline")
            next_edge = self.mesh.edge_attribute(edge, "next_edge")
            prev_edge = self.mesh.edge_attribute(edge, "prev_edge")
            next_centerline = self.mesh.edge_attribute(next_edge, "centerline")
            prev_centerline = self.mesh.edge_attribute(prev_edge, "centerline")
            # compute the vector to the end target
            _, target_end_point = intersection_line_line(centerline, next_centerline)
            vector_to_end_target = Vector.from_start_end(centerline.end, Point(*target_end_point)) * damping
            self.mesh.edge_attribute(edge, "vector_to_end_target", vector_to_end_target)
            # compute the vector to the start target
            _, target_start_point = intersection_line_line(centerline, prev_centerline)
            vector_to_start_target = Vector.from_start_end(centerline.start, Point(*target_start_point)) * damping
            self.mesh.edge_attribute(edge, "vector_to_start_target", vector_to_start_target)

    def _apply_spring_forces(self):
        """
        Applies the computed spring forces to each edge in the RF system.
        """
        for edge in self.mesh.edges():
            if self.mesh.is_edge_on_boundary(edge):
                continue
            centerline = self.mesh.edge_attribute(edge, "centerline")
            vector_to_end_target = self.mesh.edge_attribute(edge, "vector_to_end_target")
            vector_to_start_target = self.mesh.edge_attribute(edge, "vector_to_start_target")
            centerline.start += vector_to_start_target
            centerline.end += vector_to_end_target + vector_to_start_target.flipped()
            self.mesh.edge_attribute(edge, "centerline", centerline)

    def snap_centerlines_to_surface(self) -> None:
        """
        Snaps the start and end points of each centerline to the Brep surface.

        Returns
        -------
        None
        """
        for edge in self.mesh.edges():
            centerline = self.mesh.edge_attribute(edge, "centerline")
            rhino_start = Rhino.Geometry.Point3d(*centerline.start) #type: ignore
            rhino_end = Rhino.Geometry.Point3d(*centerline.end) #type: ignore
            new_start = self.brep.ClosestPoint(rhino_start)
            new_end = self.brep.ClosestPoint(rhino_end)
            centerline.start = Point(*new_start)
            centerline.end = Point(*new_end)
            self.mesh.edge_attribute(edge, "centerline", centerline)
        return None

    def extend_centerlines(self, extension: float) -> None:
        """
        Extends the centerlines of the RF system edges by a given extension value.

        Parameters
        ----------
        extension : float
            The amount by which to extend the centerlines.

        Returns
        -------
        None
        """
        for edge in self.mesh.edges():
            if self.mesh.is_edge_on_boundary(edge):
                continue
            centerline = self.mesh.edge_attribute(edge, "centerline")
            direction = centerline.direction.unitized()
            centerline.start += direction * (-extension)
            centerline.end +=direction * extension * 2
            centerline = self.mesh.edge_attribute(edge, "centerline", centerline)
        return None

    # ---- TIMBER MODEL ---- #

    def compute_timber_model(self, beam_width: float = 60, beam_height: float = 80, filter_frame=None) -> TimberModel:
        """
        Computes the timber model for the RF system.

        Parameters
        ----------
        beam_width : float, optional
            The width of the beams. Default is 60.
        beam_height : float, optional
            The height of the beams. Default is 80.
        filter_frame : Frame, optional
            A frame to filter border beams above a certain height. Default is None.

        Returns
        -------
        TimberModel
            The computed timber model.
        """
        self.timber_model = TimberModel()
        self._compute_beams(beam_width, beam_height, filter_frame)
        self._compute_joinery()
        self._computer_boundary_joinery()
        return self.timber_model

    def _compute_beams(self, beam_width: float, beam_height: float, filter_frame):
        """
        Computes the beams for the timber model based on the centerlines of the RF system edges.
        """
        for edge in self.mesh.edges():
            if filter_frame and self.mesh.is_edge_on_boundary(edge):
                midpoint = self.mesh.edge_midpoint(edge)
                if midpoint.z > filter_frame.point.z:
                    continue
            centerline = self.mesh.edge_attribute(edge, "centerline")
            normal = self.mesh.edge_attribute(edge, "normal")
            #create the beam object
            beam = Beam.from_centerline(centerline, width=beam_width, height=beam_height, z_vector=normal)
            self.timber_model.add_element(beam)
            self.mesh.edge_attribute(edge, "beam", beam)

    def _compute_joinery(self):
        """
        Computes the joinery for the timber model based on the beams of the RF system edges.
        """
        for edge in self.mesh.edges():
            if self.mesh.is_edge_on_boundary(edge):
                continue
            beam = self.mesh.edge_attribute(edge, "beam")
            next_edge = self.mesh.edge_attribute(edge, "next_edge")
            prev_edge = self.mesh.edge_attribute(edge, "prev_edge")
            next_beam = self.mesh.edge_attribute(next_edge, "beam")
            prev_beam = self.mesh.edge_attribute(prev_edge, "beam")
            if not beam:
                continue
            if self.mesh.is_edge_on_boundary(next_edge):
                if next_beam:
                    joint = TButtJoint(beam, next_beam, mill_depth=20)
                    self.timber_model.add_joint(joint)
                if prev_beam:
                    joint = XLapJoint(prev_beam, beam)
                    self.timber_model.add_joint(joint)
                continue
            if self.mesh.is_edge_on_boundary(prev_edge):
                if prev_beam:
                    joint = TButtJoint(beam, prev_beam, mill_depth=20)
                    self.timber_model.add_joint(joint)
                if next_beam:
                    joint = XLapJoint(next_beam, beam)
                    self.timber_model.add_joint(joint)
                continue
            # joint = TButtJoint(beam, next_beam)
            # self.timber_model.add_joint(joint)
            # joint = TButtJoint(beam, prev_beam)
            # self.timber_model.add_joint(joint)
            if next_beam:
                joint = XLapJoint(next_beam, beam)
                self.timber_model.add_joint(joint)
            if prev_beam:
                joint = XLapJoint(prev_beam, beam)
                self.timber_model.add_joint(joint)

    def _computer_boundary_joinery(self):
        """
        Computes the boundary joinery for the timber model based on the beams on the boundary edges of the RF system.
        """
        bedges = self.mesh.edges_on_boundary()
        for i, edge in enumerate(bedges):
            next_edge = bedges[(i + 1) % len(bedges)]
            beam = self.mesh.edge_attribute(edge, "beam")
            next_beam = self.mesh.edge_attribute(next_edge, "beam")
            if beam and next_beam:
                joint = LMiterJoint(beam, next_beam)
                self.timber_model.add_joint(joint)

    def remove_border_beams_above_frame(self, frame: Frame):
        """
        Removes beams on boundary edges that are above a given frame.

        Parameters
        ----------
        frame : Frame
            The frame used to determine which beams to remove.
        """
        for edge in self.mesh.edges():
            if not self.mesh.is_edge_on_boundary(edge):
                continue
            midpoint = self.mesh.edge_midpoint(edge)
            if midpoint.z > frame.point.z:
                self.mesh.edge_attribute(edge, "beam", None)

# ----- MULTI SURFACE MESH RELAX ---- #
class MultiSurfaceMeshRelax:
    """Relax a COMPAS :class:`compas.datastructures.Mesh` onto a Rhino Brep.

    The relaxer applies iterative, local forces to mesh vertices to improve
    mesh quality while optionally snapping vertices to a target Rhino
    :class:`Rhino.Geometry.Brep`.

    Parameters
    ----------
    mesh
        A :class:`compas.datastructures.Mesh` instance that will be modified
        in-place by the relaxer.
    brep
        A Rhino :class:`Rhino.Geometry.Brep` used for projection and
        corner attraction.
    iterations : int, optional
        Number of relaxation iterations (default: 50).
    damping : float, optional
        Global damping factor applied to computed forces (default: 0.2).
    snap_to_surface : bool, optional
        If True, moved vertices are projected back onto the Brep.
    attract_to_brep_vertices : bool, optional
        If True, vertices will be attracted to Brep face vertices.
    ignore_interior_vertices : bool, optional
        When attracting to Brep vertices, ignore those not on Brep boundary.
    snap_on_brep_edges : bool, optional
        If True and a vertex is flagged as on a Brep edge, it will snap to
        the nearest Brep interior edge.

    Attributes
    ----------
    mesh
        The mesh being relaxed.
    brep
        The target Rhino Brep.
    modifiers : list
        Registered modifier objects used to tweak mesh or force behaviour.
    assigned_vertices : set
        Temporary set used when assigning mesh vertices to Brep corners.
    boundary_vertices : list
        List of mesh vertex identifiers located on the mesh boundary.
    interior_vertices : list
        List of non-boundary (interior) mesh vertex identifiers.
    brep_face_vertices : list[list[:class:`compas.geometry.Point`]]
        List of Brep face corner vertex positions.
    brep_vertices : list[:class:`compas.geometry.Point`]
        List of all Brep vertex positions.
    brep_boundary_vertices : list[:class:`compas.geometry.Point`]
        List of Brep boundary vertex positions (naked-edge vertices).
    brep_interior_edges : list[:class:`compas.geometry.Line`]
        List of Brep interior edges as COMPAS lines.
    """

    def __init__(self, mesh,
                 brep,
                 iterations = 50,
                 damping=0.2,
                 snap_to_surface: bool = True,
                 attract_to_brep_vertices: bool = True,
                 ignore_interior_vertices: bool = True,
                 snap_on_brep_edges: bool = False) -> None:

        self.mesh = mesh
        self.brep = brep
        self.iterations = iterations
        self.damping = damping
        self.modifiers = []
        self.snap_to_surface = snap_to_surface
        self.attract_to_brep_vertices = attract_to_brep_vertices
        self.ignore_interior_vertices = ignore_interior_vertices
        self.snap_on_brep_edges = snap_on_brep_edges
        self.assigned_vertices = set()
        self._set_vertices_default_attributes()


    def _set_vertices_default_attributes(self) -> None:
        """Ensure each mesh vertex has `fixed` and `force` attributes.

        Sets `fixed` to ``False`` and `force` to a zero `compas.geometry.Vector`.
        """
        for vertex in self.mesh.vertices():
            self.mesh.vertex_attribute(vertex, "fixed", False)
            self.mesh.vertex_attribute(vertex, "force", Vector(0,0,0))
        return None


    @property
    def boundary_vertices(self):
        """Return a list of vertex identifiers located on the mesh boundary."""
        bvs = [v for v in self.mesh.vertices() if self.mesh.is_vertex_on_boundary(v)]
        return bvs

    @property
    def interior_vertices(self):
        """Return a list of non-boundary (interior) vertex identifiers."""
        ivs = [v for v in self.mesh.vertices() if not self.mesh.is_vertex_on_boundary(v)]
        return ivs


    # ---- MODIFIERS ---- #


    @property
    def brep_face_vertices(self) -> list[list[Point]]:
        """Return Brep face vertex positions as lists of :class:`compas.geometry.Point`.

        Each entry in the returned list corresponds to a single Brep face and
        contains the unique corner points discovered by iterating the face
        loops and trims.
        """
        faces_vertices = []
        for face in  self.brep.Faces:
            face_vertices = []
            vertex_ids= set()
            for loop in face.Loops:
                for trim in loop.Trims:
                    edge = trim.Edge
                    if not edge:
                        continue
                    for v in [edge.StartVertex, edge.EndVertex]:
                        if v and v.VertexIndex not in vertex_ids:
                            face_vertices.append(v.Location)
                            vertex_ids.add(v.VertexIndex)
            faces_vertices.append([Point(v.X, v.Y, v.Z) for v in face_vertices])
        return faces_vertices


    @property
    def brep_vertices(self) -> list[Point]:
        """Return a list of all Brep vertex positions as :class:`compas.geometry.Point`."""
        vertices = [v.Location for v in self.brep.Vertices]
        return [Point(v.X, v.Y, v.Z) for v in vertices]


    @property
    def brep_boundary_vertices(self) -> list[Point]:
        """Return Brep boundary vertex positions (naked-edge vertices).

        Vertices belonging to naked (boundary) edges are collected and
        returned as :class:`compas.geometry.Point` objects.
        """
        vertices = set()
        for edge in self.brep.Edges:
            if edge.Valence == rg.EdgeAdjacency.Naked:
                vertices.add(edge.StartVertex)
                vertices.add(edge.EndVertex)
        points = [v.Location for v in vertices]
        points = [Point(v.X, v.Y, v.Z) for v in points]
        return points

    @property
    def brep_interior_edges(self) -> list[Line]:
        """Return Brep interior edges as :class:`compas.geometry.Line` objects.

        Interior edges are those with adjacency different from ``Naked``.
        """
        edges = []
        for edge in self.brep.Edges:
            if edge.Valence != rg.EdgeAdjacency.Naked:
                start_point = edge.StartVertex.Location
                end_point = edge.EndVertex.Location
                edges.append(Line(Point(start_point.X, start_point.Y, start_point.Z),
                              Point(end_point.X, end_point.Y, end_point.Z)))
        return edges


    def add_modifier(self, modifier) -> None:
        """Register a modifier with the relaxer.

        Modifiers are objects exposing a `type` attribute (either
        ``'mesh_modifier'`` or ``'force_modifier'``) and an ``apply`` method.
        Mesh modifiers are applied before iterations start; force modifiers
        are applied each iteration when computing forces.
        """
        self.modifiers.append(modifier)


    # ---- RELAXATION ---- #

    def relax(self) -> Mesh:
        """Run the relaxation loop and return the relaxed mesh.

        The loop applies mesh modifiers, computes interior and boundary
        forces, optional corner attraction, force modifiers, and finally
        moves vertices according to the accumulated forces. The modified
        mesh is returned for convenience.
        """
        # Apply initial mesh modifiers (if any)
        self._apply_mesh_modifiers()
        for _ in range(self.iterations):
            self._compute_interior_forces()
            self._compute_boundary_forces()
            if self.attract_to_brep_vertices:
                self._compute_corner_forces()
            self._compute_force_modifiers()
            self._apply_forces()
        return self.mesh


    def _apply_mesh_modifiers(self) -> None:
        """Apply registered mesh modifiers before iterations begin."""
        for mod in self.modifiers:
            if mod.type == "mesh_modifier":
                self.mesh = mod.apply(self, self.mesh)


    def _compute_interior_forces(self) -> None:
        """Compute spring-like interior forces for non-boundary vertices.

        Forces are accumulated per-vertex in the `force` attribute.
        """
        for vertex in self.mesh.vertices():
            if vertex in self.boundary_vertices:
                continue
            force = self.mesh.vertex_attribute(vertex, "force")
            neighbors = self.mesh.vertex_neighbors(vertex)
            for neighbor in neighbors:
                neighbor_force = self.mesh.edge_vector((vertex, neighbor))
                force += neighbor_force * self.damping / len(neighbors)
            self.mesh.vertex_attribute(vertex, "force", force)
        return None


    def _compute_boundary_forces(self) -> None:
        """Compute forces that attract boundary vertices to target contours.

        For vertices with a `target_contour` attribute, compute the closest
        point on that contour and add a damped attraction force.
        """
        for vertex in self.boundary_vertices:

            if self.mesh.vertex_attribute(vertex, "not_boundary"):
                continue

            boundary = self.mesh.vertex_attribute(vertex, "target_contour")
            if boundary is None:
                continue
            vertex_point = self.mesh.vertex_point(vertex)
            try:
                projected_point = Point(
                    *closest_point_on_polyline(vertex_point, boundary)
                )
            except (TypeError, ValueError):
                # Skip if boundary is invalid
                continue

            force = self.mesh.vertex_attribute(vertex, "force")
            bforce = Vector.from_start_end(vertex_point, projected_point)
            bforce *= self.damping
            force += bforce
            self.mesh.vertex_attribute(vertex, "force", force)
        return None



    def _compute_corner_forces(self) -> None:
        """Attract selected mesh vertices toward Brep face corner points.

        For each Brep face corner the closest mesh boundary vertex (not
        already assigned) is found and given a stronger damped attraction
        force toward that corner point.
        """
        self.mesh.remove_unused_vertices()
        self.assigned_vertices = set()
        for face in self.brep_face_vertices:
            for point in face:
                if self.ignore_interior_vertices and point not in self.brep_boundary_vertices:
                    continue
                # find the closes boundary vertex,
                # if the vertex has already been assigned, nevermind, just go on
                closest_vertex = min(self.mesh.vertices(), key=lambda v: self.mesh.vertex_point(v).distance_to_point(point))
                if closest_vertex in self.assigned_vertices:
                    continue
                self.assigned_vertices.add(closest_vertex)
                # compute the force toward the corner
                vertex_point = self.mesh.vertex_point(closest_vertex)
                corner_force = Vector.from_start_end(vertex_point, point) * self.damping * 2
                # add the corner force to the existing force of the vertex
                force = self.mesh.vertex_attribute(closest_vertex, "force")
                force += corner_force
                self.mesh.vertex_attribute(closest_vertex, "force", force)
        return None


    def  _compute_force_modifiers(self) -> None:
        """Apply registered force modifiers to update per-vertex forces."""
        for mod in self.modifiers:
            if mod.type == "force_modifier":
                self.mesh = mod.apply(self, self.mesh)
        return None


    def _apply_forces(self) -> None:
        """Move mesh vertices using the accumulated `force` attributes.

        Forces are optionally projected onto the Brep or snapped to Brep
        interior edges. Vertices flagged as `fixed` are not moved.
        """
        print("Applying forces to mesh vertices...")
        for vertex in self.mesh.vertices():
             # get the force and compute the new point poistion of the vertex
            force = self.mesh.vertex_attribute(vertex, "force")

            vertex_point = self.mesh.vertex_point(vertex)
            new_point = vertex_point + force

            # project the new point onto the brep if required
            if self.snap_to_surface:
                closest_point = self.brep.ClosestPoint(rg.Point3d(new_point.x, new_point.y, new_point.z))
                if closest_point:
                    new_point = Point(closest_point.X, closest_point.Y, closest_point.Z)

            if self.snap_on_brep_edges and self.mesh.vertex_attribute(vertex, "on_brep_edge"):
                edges = self.brep_interior_edges
                closest_edge = min(edges, key=lambda e: distance_point_line(new_point, e))
                new_point = Point(*closest_point_on_line(new_point, closest_edge))

            if self.mesh.vertex_attribute(vertex, "fixed"): # the vertex is fixed, do not move it
                continue

            # update the vertex position
            self.mesh.vertex_attribute(vertex, "x", new_point.x)
            self.mesh.vertex_attribute(vertex, "y", new_point.y)
            self.mesh.vertex_attribute(vertex, "z", new_point.z)
        return None



