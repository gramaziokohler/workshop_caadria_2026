from compas.geometry import Frame
from compas.geometry import Transformation
from compas_rhino.conversions import point_to_compas


def basic_arrange_beams(timber_model, origin, gap):
    origin = point_to_compas(point)

    frame = Frame(origin, [0, 1, 0], [0, 0, 1])
    beam_grid = []
    for i, beam in enumerate(timber_model.beams):
        stock_beam = beam.geometry
        trans = Transformation.from_frame_to_frame(beam.frame, frame)
        stock_beam = stock_beam.transformed(trans)
        beam_grid.append(stock_beam)
        frame.point.x += gap


def get_general_stats(timber_model, wood_density=500):
    """
    Erstellt allgemeine Statistiken über das Timber-Modell.
    wood_density: Dichte in kg/m3 (Standard ca. 500 für Nadelholz)
    """
    beams = list(timber_model.beams)

    # 1. Basis Geometrie
    count = len(beams)
    lengths = [b.centerline.length for b in beams]
    total_length = sum(lengths)
    min_len = min(lengths) if lengths else 0
    max_len = max(lengths) if lengths else 0

    # 2. Masse (Volumen & Gewicht)
    total_volume = sum(b.geometry.volume for b in beams)
    total_weight = total_volume * wood_density

    # 3. Features & Bearbeitungen
    total_joints = sum(len(b.joints) for b in beams if hasattr(b, "joints"))
    total_features = sum(len(b.features) for b in beams if hasattr(b, "features"))

    stats_msg = "\n".join(
        [
            "--- MODEL STATS ---",
            f"Beams: {count}",
            f"Total Length: {total_length:.2f} m",
            f"Weight: {total_weight:.1f} kg",
            f"Joints/Features: {total_joints} / {total_features}",
            "-------------------",
        ]
    )

    print(stats_msg)

    return stats_msg


def solve_bin_packing(timber_model, stock_length, saw_kerf=0.0):
    """
    Kerns-Logik für Bin Packing (First Fit Decreasing).

    Returns:
        list: Liste von Dictionaries (Stocks), die jeweils die gepackten Balken enthalten.
    """
    # 1. Daten extrahieren und vorbereiten
    beams = list(timber_model.beams)
    beam_data = []
    for i, beam in enumerate(beams):
        l = beam.centerline.length
        beam_data.append({"beam": beam, "original_index": i, "length": l, "needed_len": l + saw_kerf})

    # 2. Sortieren: Längste Balken zuerst (First Fit Decreasing)
    sorted_beams = sorted(beam_data, key=lambda x: x["length"], reverse=True)

    stocks = []

    # 3. Packing Loop
    for item in sorted_beams:
        needed = item["needed_len"]
        placed = False

        # Versuche in existierende Stocks einzufügen
        for stock in stocks:
            if stock["remaining"] >= needed:
                # Add to stock
                current_start = stock["current_pos"]
                stock["beams"].append({"beam": item["beam"], "start_pos": current_start, "length": item["length"]})

                # Update stock stats
                stock["remaining"] -= needed
                stock["current_pos"] += needed
                placed = True
                break

        if not placed:
            # Erstelle neuen Stock
            new_stock = {
                "id": len(stocks),
                "remaining": stock_length - needed,
                "current_pos": needed,
                "beams": [{"beam": item["beam"], "start_pos": 0.0, "length": item["length"]}],
            }
            stocks.append(new_stock)

    return stocks


def visualize_packing(stocks, origin, stock_length, beam_spacing=0.6, beam_offset=0.2):
    """
    Erzeugt Visualisierungs-Geometrie aus dem Packing-Resultat.

    Args:
        stocks (list): Das Ergebnis von solve_bin_packing.
        origin (Point): Startpunkt für die Visualisierung.
        stock_length (float): Die visuelle Länge der Rohbalken.
        beam_spacing (float): Abstand zwischen den Rohbalken in Y.
        beam_offset (float): Abstand der gepackten Balken zum Rohbalken in Y.

    Returns:
        tuple: (stock_geometries, packed_beam_geometries)
    """
    # Imports falls nötig (hier gehen wir davon aus, dass sie im Scope sind,
    # aber sicherheitshalber importieren wir Transformation und Frame für die Logik)
    from compas.geometry import Box
    from compas.geometry import Frame
    from compas.geometry import Line
    from compas.geometry import Point
    from compas.geometry import Transformation
    from compas.geometry import Vector

    visual_stocks = []
    visual_beams = []

    base_x = origin.x
    base_y = origin.y
    base_z = origin.z

    for i, stock in enumerate(stocks):
        y_pos = base_y + (i * beam_spacing)

        # 1. Erzeuge Stock-Geometrie (als Hintergrund)
        # Wir nutzen width/height des ersten Balkens im Stock als Referenz
        if stock["beams"]:
            ref_beam = stock["beams"][0]["beam"]
            w = ref_beam.width
            h = ref_beam.height
        else:
            w, h = 0.1, 0.1

        # Erstelle Box Geometrie für den Stock
        # Box Zentrum berechnen
        center_x = base_x + stock_length / 2
        center_pt = Point(center_x, y_pos, base_z)

        # Frame für die Box (Zentrum)
        box_frame = Frame(center_pt, Vector(1, 0, 0), Vector(0, 1, 0))

        # Box(xsize, ysize, zsize, frame)
        # xsize ist hier die Länge des Stocks
        stock_box = Box(stock_length, w, h, frame=box_frame)
        visual_stocks.append(stock_box)

        # 2. Transformiere die gepackten Balken
        for item in stock["beams"]:
            beam = item["beam"]
            start_x = base_x + item["start_pos"]

            # Ziel-Frame:
            # Position: start_x, y_pos + offset, base_z
            # Orientierung: Global X
            target_pt = Point(start_x, y_pos + beam_offset, base_z)
            target_frame = Frame(target_pt, Vector(1, 0, 0), Vector(0, 1, 0))

            # Quell-Frame des Balkens
            source_frame = beam.frame

            # Transformation
            X = Transformation.from_frame_to_frame(source_frame, target_frame)

            # Geometrie kopieren und transformieren
            if hasattr(beam, "geometry") and beam.geometry:
                new_geo = beam.geometry.transformed(X)
                visual_beams.append(new_geo)

    return visual_stocks, visual_beams


def get_packing_stats(stocks, stock_length, price_per_meter=5.00, currency="CHF"):
    """
    Erzeugt einen Bericht über die Effizienz und Kosten des Packings.
    """
    if not stocks:
        return {}

    # 1. Basis Werte
    num_stocks = len(stocks)
    total_stock_bought = num_stocks * stock_length

    # 2. Verschnitt Berechnung
    # Wir summieren den 'remaining' Wert jedes Stocks
    total_waste = sum(stock["remaining"] for stock in stocks)
    used_length = total_stock_bought - total_waste

    # 3. Effizienz
    efficiency = 0
    if total_stock_bought > 0:
        efficiency = (used_length / total_stock_bought) * 100

    # 4. Kosten
    total_cost = total_stock_bought * price_per_meter

    # Ausgabe formatieren

    msg = "\n".join(
        [
            "--- PACKING REPORT ---",
            f"Stock Length used: {stock_length} m",
            f"Stocks needed:     {num_stocks} pcs",
            f"Total Material:    {total_stock_bought:.2f} m",
            "----------------------",
            f"Total Waste:       {total_waste:.2f} m",
            f"Efficiency:        {efficiency:.1f}%",
            "----------------------",
            f"Price/m:           {price_per_meter} {currency}",
            f"ESTIMATED COST:    {total_cost:.2f} {currency}",
            "----------------------",
        ]
    )

    print(msg)

    # Rückgabe als String für Text Panel
    return msg
