from flask import Flask, request, jsonify, send_from_directory
import heapq
import math
import os
import random
import re


app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


# =========================================================
# ROOM RANGES
# =========================================================

room_ranges = {

    "A": {
        0: [(43, 54)],
        1: [(146, 157)],
        2: [(241, 251)],
        3: [(342, 356)],
        4: [(437, 450)],
        5: [(542, 555)],
        6: [(642, 656)],
        7: [(742, 752)],
    },

    # B block is two hexagons (formerly mislabeled "second row
    # right" and "third row right"), joined into one wing.
    "B": {
        0: [(1, 7), (17, 21)],
        1: [(101, 108), (119, 124)],
        2: [(201, 207), (219, 222)],
        3: [(301, 307), (317, 321)],
        4: [(401, 406), (413, 416)],
        5: [(501, 506), (518, 521)],
        6: [(601, 604), (615, 620)],
        7: [(701, 705), (716, 721)],
    },

    # D block is two hexagons (formerly mislabeled "second row
    # left" and "third row left"), joined into one wing.
    "D": {
        0: [(8, 13), (22, 28)],
        1: [(108, 113), (125, 131)],
        2: [(208, 212), (222, 229)],
        3: [(307, 311), (321, 326)],
        4: [(406, 410), (417, 421)],
        5: [(507, 511), (522, 526)],
        6: [(605, 609), (621, 626)],
        7: [(706, 713), (722, 728)],
    },

    # M is the Main Entrance hexagon, sitting between the D and B
    # wings, next to the PRP Canteen.
    "M": {
        0: [(14, 16)],
        1: [(115, 116)],
        2: [(213, 218)],
        3: [(312, 316)],
        4: [(411, 413)],
        5: [(512, 517)],
        6: [(610, 610)],
        7: [(714, 715)],
    },

    # F is the bottom hexagon below the Main Entrance. It has no
    # rooms on the ground floor and no rooms on floor 7.
    "F": {
        1: [(117, 117)],
        2: [(216, 217)],
        3: [(315, 315)],
        4: [(412, 412)],
        5: [(513, 516)],
        6: [(611, 614)],
    },

    "E": {
        0: [(31, 42)],
        1: [(134, 145)],
        2: [(230, 240)],
        3: [(329, 341)],
        4: [(424, 436)],
        5: [(529, 541)],
        6: [(629, 641)],
        7: [(731, 741)],
    },
}


building_names = {
    "A": "A Block",
    "B": "B Block",
    "D": "D Block",
    "E": "E Block",
    "F": "F Block",
    "M": "Main Entrance",
}


# Building letters actually in use, used to build the room-lookup
# regex below. Kept dynamic so adding/removing a building doesn't
# require touching the parsing logic separately.
BUILDING_LETTERS = "".join(sorted(room_ranges.keys()))


# =========================================================
# CANVAS
#
# Size of the per-floor SVG coordinate space. Made large and
# roomy on purpose: pods sit far enough apart that the corridor
# line connecting them reads as a real, visible connection
# rather than the pods looking like one packed-together block.
# =========================================================

CANVAS_WIDTH = 1400

CANVAS_HEIGHT = 900


# =========================================================
# EXPAND ROOM RANGES
# =========================================================

def expand_ranges(ranges):

    rooms = []

    for start, end in ranges:

        for number in range(start, end + 1):

            rooms.append(number)

    return rooms


# =========================================================
# ROOM LIST
# =========================================================

rooms_by_floor = {}

for building, floors in room_ranges.items():

    rooms_by_floor[building] = {}

    for floor, ranges in floors.items():

        rooms_by_floor[building][floor] = \
            expand_ranges(ranges)


# =========================================================
# GRAPH
# =========================================================

graph = {}


def add_node(node):

    if node not in graph:

        graph[node] = {}


def add_edge(
    node1,
    node2,
    distance,
    direction,
    reverse_direction=None,
    route_type="indoor"
):

    add_node(node1)
    add_node(node2)

    graph[node1][node2] = {
        "distance": distance,
        "direction": direction,
        "route_type": route_type
    }

    graph[node2][node1] = {
        "distance": distance,
        "direction": reverse_direction or direction,
        "route_type": route_type
    }


# =========================================================
# POSITIONS
# =========================================================

positions = {}


# =========================================================
# GENERATE ROOM POSITIONS
# =========================================================

# =========================================================
# CURVED CORRIDOR SPINE
#
# Each pod's rooms sit along a single bending corridor line
# (a quadratic curve) rather than fixed hexagon vertices - closer
# to how a real hallway bends around a building's footprint.
# Rooms cluster in small pairs that bulge slightly off the spine
# to each side, instead of sitting in one strict file, echoing how
# real classrooms bunch up along a corridor rather than lining up
# perfectly on a single centerline.
#
# The bend direction/amount is randomized but seeded deterministically
# per building+floor+pod, so re-generating the app always produces
# the same layout, while still giving every pod its own loose,
# organic curve rather than a rigid repeated shape.
# =========================================================

def curved_corridor_points(
    center_x,
    center_y,
    width,
    height,
    count,
    seed
):

    if count <= 0:

        return []

    rng = random.Random(seed)

    # Endpoints of the corridor spine, with a small vertical jitter
    # so consecutive pods don't all look identical.
    start_y = center_y + rng.uniform(-0.18, 0.18) * height

    end_y = center_y + rng.uniform(-0.18, 0.18) * height

    p0 = (center_x - width / 2, start_y)

    p2 = (center_x + width / 2, end_y)

    # Bend the spine up or down, loosely echoing the way the real
    # building outlines curve rather than running perfectly straight.
    bend_direction = 1 if rng.random() < 0.5 else -1

    bend_amount = height * rng.uniform(0.30, 0.55)

    control_x = (p0[0] + p2[0]) / 2

    control_y = (
        (p0[1] + p2[1]) / 2
        + bend_direction * bend_amount
    )

    perp_amplitude = min(18, height * 0.22)

    points = []

    for index in range(count):

        t = 0.5 if count == 1 else index / (count - 1)

        one_minus_t = 1 - t

        # Point on the quadratic bezier spine.
        x = (
            one_minus_t ** 2 * p0[0]
            + 2 * one_minus_t * t * control_x
            + t ** 2 * p2[0]
        )

        y = (
            one_minus_t ** 2 * p0[1]
            + 2 * one_minus_t * t * control_y
            + t ** 2 * p2[1]
        )

        # Tangent direction at this point, used to offset the room
        # sideways off the spine rather than along it.
        tangent_x = (
            2 * one_minus_t * (control_x - p0[0])
            + 2 * t * (p2[0] - control_x)
        )

        tangent_y = (
            2 * one_minus_t * (control_y - p0[1])
            + 2 * t * (p2[1] - control_y)
        )

        tangent_length = math.hypot(tangent_x, tangent_y) or 1

        perp_x = -tangent_y / tangent_length

        perp_y = tangent_x / tangent_length

        # Rooms bulge off the spine in alternating pairs, matching
        # the little clustered squares in the reference sketch.
        cluster_side = 1 if (index // 2) % 2 == 0 else -1

        offset = perp_amplitude * cluster_side

        points.append((
            x + perp_x * offset,
            y + perp_y * offset
        ))

    return points


# =========================================================
# GENERATE ROOM POSITIONS
#
# Each entry in `ranges` is one physically annotated pod (matching
# an individual hexagon marked on the campus map), not an arbitrary
# chunk of six. Every pod's rooms are laid out along their own
# curved corridor. When a floor has more than one pod, the pods
# are chained left to right with real gaps between them - the
# corridor edge connecting the last room of one pod to the first
# room of the next (already created elsewhere) then reads as a
# visible line bridging that gap.
# =========================================================

def perimeter_points(count, cx, cy, width, height, shape="rectangle", rotation=-math.pi / 2):
    """Place room centers evenly around a closed perimeter."""
    if count <= 0:
        return []
    if count == 1:
        return [(cx, cy)]

    points = []
    if shape == "hexagon":
        vertices = []
        rx = width / 2
        ry = height / 2
        for i in range(6):
            angle = rotation + i * math.pi / 3
            vertices.append((cx + rx * math.cos(angle),
                            cy + ry * math.sin(angle)))

        # Walk equal distances along the six sides.
        lengths = []
        total = 0.0
        for i in range(6):
            a = vertices[i]
            b = vertices[(i + 1) % 6]
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            lengths.append(length)
            total += length

        for n in range(count):
            d = total * n / count
            acc = 0.0
            for i, length in enumerate(lengths):
                if d <= acc + length or i == 5:
                    a = vertices[i]
                    b = vertices[(i + 1) % 6]
                    t = 0 if length == 0 else (d - acc) / length
                    points.append((
                        a[0] + (b[0] - a[0]) * t,
                        a[1] + (b[1] - a[1]) * t,
                    ))
                    break
                acc += length
        return points

    # Rectangle: distribute rooms equally along the four sides.
    half_w = width / 2
    half_h = height / 2
    corners = [
        (cx - half_w, cy - half_h),
        (cx + half_w, cy - half_h),
        (cx + half_w, cy + half_h),
        (cx - half_w, cy + half_h),
    ]
    lengths = [width, height, width, height]
    total = sum(lengths)
    for n in range(count):
        d = total * n / count
        acc = 0.0
        for i, length in enumerate(lengths):
            if d <= acc + length or i == 3:
                a = corners[i]
                b = corners[(i + 1) % 4]
                t = 0 if length == 0 else (d - acc) / length
                points.append((
                    a[0] + (b[0] - a[0]) * t,
                    a[1] + (b[1] - a[1]) * t,
                ))
                break
            acc += length
    return points


def generate_room_positions(building, floor, ranges):
    """Generate floor layouts matching each block's physical footprint."""
    room_numbers = expand_ranges(ranges)
    count = len(room_numbers)

    margin = 80
    cx = CANVAS_WIDTH / 2 + 50
    cy = CANVAS_HEIGHT / 2
    width = min(900, CANVAS_WIDTH - 320)
    height = min(620, CANVAS_HEIGHT - 220)

    # A and E are enclosed rectangular blocks.
    # B and D are enclosed hexagonal blocks.
    if building in ("A", "E"):
        points = perimeter_points(
            count, cx, cy, width, height, shape="rectangle"
        )
    elif building in ("B", "D"):
        points = perimeter_points(
            count, cx, cy, width * 0.92, height * 0.82, shape="hexagon"
        )
    else:
        # Keep M/F as compact organic single-pod layouts.
        points = curved_corridor_points(
            cx, cy, width * 0.62, height * 0.55,
            count, seed=f"{building}-{floor}"
        )

    for room_number, (x, y) in zip(room_numbers, points):
        node_name = f"{building}-{room_number}"
        positions[node_name] = {
            "x": x,
            "y": y,
            "floor": floor,
            "building": building,
            "type": "room",
            "room_number": room_number,
        }

    # Put the staircase just outside the left side of the footprint.
    return (margin, cy)


# =========================================================
# CREATE ROOM POSITIONS
# =========================================================

stair_positions = {}

for building, floors in \
        room_ranges.items():

    for floor, ranges in \
            floors.items():

        stair_x, stair_y = generate_room_positions(
            building,
            floor,
            ranges
        )

        stair_positions[(building, floor)] = (stair_x, stair_y)


# =========================================================
# STAIR POSITIONS
#
# Every floor has a staircase node.
# =========================================================

for building in room_ranges:

    for floor in range(8):

        stair_node = (
            f"{building}-STAIRS-{floor}"
        )

        stair_x, stair_y = stair_positions.get(
            (building, floor),
            # fallback for a floor with no room data
            (CANVAS_WIDTH / 2, CANVAS_HEIGHT / 2)
        )

        positions[stair_node] = {

            "x": stair_x,

            "y": stair_y,

            "floor": floor,

            "building": building,

            "type": "stairs"

        }


# =========================================================
# ENTRANCE
# =========================================================

for building in room_ranges:

    entrance_node = (
        f"{building}-ENTRANCE"
    )

    positions[entrance_node] = {

        "x": 60,

        "y": CANVAS_HEIGHT - 80,

        "floor": 0,

        "building": building,

        "type": "entrance"

    }


# =========================================================
# CONNECT ROOMS
# =========================================================

for building, floors in \
        room_ranges.items():

    for floor, ranges in \
            floors.items():

        room_numbers = expand_ranges(ranges)

        # -------------------------------------------------
        # Connect rooms in sequence
        #
        # This also connects the last room of one pod to the
        # first room of the next pod, which is exactly the
        # corridor line that should bridge the gap between two
        # neighbouring hexagons.
        # -------------------------------------------------

        for i in range(len(room_numbers)):
            room1 = f"{building}-{room_numbers[i]}"
            room2 = f"{building}-{room_numbers[(i + 1) % len(room_numbers)]}"

            # The final room connects back to the first room so A/E
            # rectangles and B/D hexagons are real closed corridors.
            if room1 != room2:
                add_edge(
                    room1,
                    room2,
                    3,
                    "follow the corridor"
                )

        # A and E are closed circular corridors, so connect the last
        # room back to the first room as well. This makes the visible
        # corridor a true closed loop and allows routing around either
        # side of the circle.
        if building in ("A", "E") and len(room_numbers) > 2:
            add_edge(
                f"{building}-{room_numbers[-1]}",
                f"{building}-{room_numbers[0]}",
                3,
                "follow the circular corridor"
            )

        # -------------------------------------------------
        # Connect staircase to first room
        # -------------------------------------------------

        if room_numbers:

            first_room = (
                f"{building}-{room_numbers[0]}"
            )

            stairs = (
                f"{building}-STAIRS-{floor}"
            )

            add_edge(
                stairs,
                first_room,
                5,
                "walk from the staircase into the corridor"
            )


# =========================================================
# ENTRANCE -> GROUND FLOOR STAIRS
# =========================================================

for building in room_ranges:

    entrance = (
        f"{building}-ENTRANCE"
    )

    stairs = (
        f"{building}-STAIRS-0"
    )

    add_edge(
        entrance,
        stairs,
        5,
        "enter the building"
    )


# =========================================================
# CONNECT BUILDINGS: CAMPUS WALKWAY
#
# Physical layout of the PRP complex: E and A are the two large
# blocks at the top, side by side. Below E sits the D wing, below
# A sits the B wing, and the Main Entrance (M) hexagon sits
# between D and B. The F wing hangs below M. Each outdoor edge
# joins the two building entrances, allowing a route to continue
# naturally from one block to the next:
#
#         E                       A
#         |                       |
#         D --------- M --------- B
#                      |
#                      F
# =========================================================

campus_walkways = [
    ("E", "D", 14),
    ("D", "M", 10),
    ("M", "B", 10),
    ("B", "A", 14),
    ("M", "F", 8),
]

for from_building, to_building, distance in campus_walkways:

    add_edge(
        f"{from_building}-ENTRANCE",
        f"{to_building}-ENTRANCE",
        distance,
        (
            f"exit {building_names[from_building]} and "
            f"follow the outdoor walkway to "
            f"{building_names[to_building]}"
        ),
        (
            f"exit {building_names[to_building]} and "
            f"follow the outdoor walkway to "
            f"{building_names[from_building]}"
        ),
        route_type="outdoor"
    )

    add_edge(
        f"{from_building}-STAIRS-0",
        f"{to_building}-STAIRS-0",
        distance - 4,
        (
            f"take the covered indoor connector to "
            f"{building_names[to_building]}"
        ),
        (
            f"take the covered indoor connector to "
            f"{building_names[from_building]}"
        ),
        route_type="covered"
    )


# =========================================================
# CONNECT FLOORS
#
# IMPORTANT:
#
# Each floor has its own staircase node.
#
# Floor 1:
# C-STAIRS-1
#
# Floor 2:
# C-STAIRS-2
#
# etc.
#
# Therefore the route explicitly contains EVERY
# floor transition.
# =========================================================

for building in room_ranges:

    for floor in range(7):

        current_stairs = (
            f"{building}-STAIRS-{floor}"
        )

        next_stairs = (
            f"{building}-STAIRS-{floor + 1}"
        )

        add_edge(
            current_stairs,
            next_stairs,
            8,
            "use the staircase"
        )


# =========================================================
# ORIENTATION
# =========================================================

orientation = {}


for building in room_ranges:

    orientation[
        f"{building}-ENTRANCE"
    ] = (
        "Enter the building."
    )

    for floor in range(8):

        orientation[
            f"{building}-STAIRS-{floor}"
        ] = (
            "Use the staircase."
        )


# =========================================================
# DIJKSTRA
# =========================================================

def shortest_path(
    graph,
    start,
    end,
    avoid_route_types=None
):

    if start not in graph:

        return None

    if end not in graph:

        return None

    distances = {

        node:
            float("inf")

        for node in graph
    }

    distances[start] = 0

    previous = {

        node:
            None

        for node in graph
    }

    visited = set()

    queue = [
        (0, start)
    ]

    while queue:

        current_distance, current_node = \
            heapq.heappop(queue)

        if current_node in visited:

            continue

        visited.add(
            current_node
        )

        if current_node == end:

            break

        for neighbor, edge in \
                graph[current_node].items():

            if (
                avoid_route_types
                and edge.get("route_type")
                in avoid_route_types
            ):

                continue

            new_distance = (
                current_distance
                +
                edge["distance"]
            )

            if new_distance < \
                    distances[neighbor]:

                distances[neighbor] = \
                    new_distance

                previous[neighbor] = \
                    current_node

                heapq.heappush(
                    queue,
                    (
                        new_distance,
                        neighbor
                    )
                )

    if distances[end] == \
            float("inf"):

        return None

    path = []

    node = end

    while node is not None:

        path.append(node)

        node = previous[node]

    path.reverse()

    return path


# =========================================================
# DIRECTIONS
# =========================================================

def get_directions(
    graph,
    path
):

    instructions = []

    if not path:

        return instructions

    for i in range(
        len(path) - 1
    ):

        current = path[i]

        next_node = path[i + 1]

        current_pos = \
            positions[current]

        next_pos = \
            positions[next_node]

        # -------------------------------------------------
        # FLOOR CHANGE
        # -------------------------------------------------

        if (
            current_pos["floor"]
            !=
            next_pos["floor"]
        ):

            if (
                next_pos["floor"]
                >
                current_pos["floor"]
            ):

                instructions.append(
                    f"At {current}, "
                    f"go UP to Floor "
                    f"{next_pos['floor']}."
                )

            else:

                instructions.append(
                    f"At {current}, "
                    f"go DOWN to Floor "
                    f"{next_pos['floor']}."
                )

            continue

        # -------------------------------------------------
        # NORMAL MOVEMENT
        # -------------------------------------------------

        edge = \
            graph[current][next_node]

        instructions.append(
            f"From {current}, "
            f"{edge['direction']} "
            f"towards {next_node}."
        )

    instructions.append(
        f"You have arrived at {path[-1]}."
    )

    return instructions


# =========================================================
# ROOM NORMALIZATION
#
# IMPORTANT:
#
# User can enter:
#
# 43
# A43
# A-43
# A 43
# D108
# D-108
# D 108
#
# Bare numbers are supported.
#
# Building letters are read from BUILDING_LETTERS so this stays
# correct if buildings are ever added, removed, or renamed.
# =========================================================

def normalize_room(
    room
):

    if not room:

        return None

    value = (
        str(room)
        .strip()
        .upper()
    )

    # -----------------------------------------------------
    # Normalize separators
    # -----------------------------------------------------

    value = value.replace(
        "/",
        "-"
    )

    value = value.replace(
        " ",
        "-"
    )

    while "--" in value:

        value = value.replace(
            "--",
            "-"
        )

    # -----------------------------------------------------
    # Direct graph lookup
    # -----------------------------------------------------

    if value in graph:

        return value

    # -----------------------------------------------------
    # A43 -> A-43
    # D108 -> D-108
    # -----------------------------------------------------

    match = re.fullmatch(
        rf"([{BUILDING_LETTERS}])[-]?(\d+)",
        value
    )

    if match:

        building = \
            match.group(1)

        room_number = \
            match.group(2)

        candidate = (
            f"{building}-{room_number}"
        )

        if candidate in graph:

            return candidate

    # -----------------------------------------------------
    # BARE ROOM NUMBER
    #
    # Example:
    #
    # 43 -> A-43
    #
    # 163 -> B-163
    #
    # 101 -> C-101
    # -----------------------------------------------------

    if value.isdigit():

        room_number = int(value)

        matches = []

        for building in room_ranges:

            candidate = (
                f"{building}-{room_number}"
            )

            if candidate in graph:

                matches.append(
                    candidate
                )

        # ---------------------------------------------
        # Exactly one matching room
        # ---------------------------------------------

        if len(matches) == 1:

            return matches[0]

        # ---------------------------------------------
        # Ambiguous room
        # ---------------------------------------------

        if len(matches) > 1:

            return None

    return None


# =========================================================
# HOME
# =========================================================

@app.route("/")
def home():

    return send_from_directory(
        BASE_DIR,
        "index.html"
    )


# =========================================================
# CAMPUS MAP
# =========================================================

@app.route("/campus_map.png")
def campus_map():

    return send_from_directory(
        BASE_DIR,
        "campus_map.png"
    )


# =========================================================
# PATH
# =========================================================

@app.route("/path")
def get_path():

    raw_start = request.args.get(
        "from",
        ""
    )

    raw_end = request.args.get(
        "to",
        ""
    )

    raw_via = request.args.get(
        "via"
    )

    route_mode = request.args.get(
        "mode",
        "indoor"
    ).lower()

    if route_mode not in {"indoor", "outdoor"}:

        return jsonify({

            "error": "Route mode must be 'indoor' or 'outdoor'."

        }), 400

    avoid_route_types = (
        {"outdoor"}
        if route_mode == "indoor"
        else {"covered"}
    )

    start = normalize_room(
        raw_start
    )

    end = normalize_room(
        raw_end
    )

    via = (
        normalize_room(raw_via)
        if raw_via
        else None
    )

    # -----------------------------------------------------
    # Validate From
    # -----------------------------------------------------

    if not start:

        return jsonify({

            "error":
                f"Could not identify starting room "
                f"'{raw_start}'. "
                f"Enter a room number such as 43, 101, "
                f"or a block-qualified room such as C101."

        }), 400

    # -----------------------------------------------------
    # Validate To
    # -----------------------------------------------------

    if not end:

        return jsonify({

            "error":
                f"Could not identify destination room "
                f"'{raw_end}'."

        }), 400

    # -----------------------------------------------------
    # VIA
    # -----------------------------------------------------

    if raw_via and not via:

        return jsonify({

            "error":
                f"Could not identify stop room "
                f"'{raw_via}'."

        }), 400

    # -----------------------------------------------------
    # Route with VIA
    # -----------------------------------------------------

    if via:

        first_leg = shortest_path(
            graph,
            start,
            via,
            avoid_route_types
        )

        second_leg = shortest_path(
            graph,
            via,
            end,
            avoid_route_types
        )

        if first_leg is None:

            return jsonify({

                "error":
                    f"No path found between "
                    f"{start} and {via}"

            }), 404

        if second_leg is None:

            return jsonify({

                "error":
                    f"No path found between "
                    f"{via} and {end}"

            }), 404

        result = (
            first_leg
            +
            second_leg[1:]
        )

    else:

        result = shortest_path(
            graph,
            start,
            end,
            avoid_route_types
        )

        if result is None:

            return jsonify({

                "error":
                    f"No path found between "
                    f"{start} and {end}"

            }), 404

    # =====================================================
    # PATH COORDINATES
    # =====================================================

    path_coords = []

    for index, node in \
            enumerate(result):

        if node not in positions:

            continue

        pos = positions[node]

        # -------------------------------------------------
        # Determine next node
        # -------------------------------------------------

        next_node = None

        if index < len(result) - 1:

            next_node = \
                result[index + 1]

        # -------------------------------------------------
        # Determine whether this is a floor transition
        # -------------------------------------------------

        is_floor_transition = False

        next_floor = None

        next_route_type = None

        if next_node and \
                next_node in positions:

            next_pos = \
                positions[next_node]

            if (
                next_pos["floor"]
                !=
                pos["floor"]
            ):

                is_floor_transition = \
                    True

                next_floor = \
                    next_pos["floor"]

            if (
                next_pos["building"]
                != pos["building"]
            ):

                next_route_type = \
                    graph[node][next_node].get(
                        "route_type"
                    )

        path_coords.append({

            "name": node,

            "x": pos["x"],

            "y": pos["y"],

            "floor": pos["floor"],

            "building":
                pos["building"],

            "type":
                pos.get(
                    "type",
                    "node"
            ),

            "room_number":
                pos.get(
                    "room_number"
            ),

            "is_floor_transition":
                is_floor_transition,

            "next_floor":
                next_floor,

            "next_route_type":
                next_route_type,

            "is_stop":
                bool(via and node == via)

        })

    return jsonify({

        "from":
            start,

        "to":
            end,

        "via":
            via,

        "route_mode":
            route_mode,

        "available_modes": (
            ["indoor", "outdoor"]
            if positions[start]["building"]
            != positions[end]["building"]
            else []
        ),

        "path":
            result,

        "steps":
            max(
                0,
                len(result) - 1
        ),

        "path_coords":
            path_coords,

        "directions":
            get_directions(
                graph,
                result
        )

    })


# =========================================================
# ROOMS
# =========================================================

@app.route("/rooms")
def get_rooms():

    rooms = []

    for building, floors in \
            rooms_by_floor.items():

        for floor, room_numbers in \
                floors.items():

            for room_number in \
                    room_numbers:

                rooms.append({

                    "name":
                        f"{building}-{room_number}",

                    "building":
                        building,

                    "floor":
                        floor,

                    "room":
                        room_number

                })

    return jsonify({

        "rooms":
            rooms

    })


# =========================================================
# FLOOR
# =========================================================

@app.route("/floor")
def get_floor():

    building = request.args.get(
        "building",
        "A"
    ).upper()

    try:

        floor_num = int(
            request.args.get(
                "floor",
                "0"
            )
        )

    except ValueError:

        floor_num = 0

    if building not in room_ranges:

        return jsonify({

            "error":
                "Unknown building"

        }), 404

    if floor_num not in \
            room_ranges[building]:

        return jsonify({

            "error":
                "Unknown floor"

        }), 404

    nodes_on_floor = {}

    for node, pos in \
            positions.items():

        if (
            pos["building"]
            ==
            building
            and
            pos["floor"]
            ==
            floor_num
        ):

            nodes_on_floor[node] = pos

    edges = []

    seen = set()

    for node in graph:

        if node not in \
                nodes_on_floor:

            continue

        for neighbor in \
                graph[node]:

            if neighbor not in \
                    nodes_on_floor:

                continue

            pair = tuple(
                sorted(
                    [node, neighbor]
                )
            )

            if pair not in seen:

                seen.add(pair)

                edges.append({

                    "from":
                        pair[0],

                    "to":
                        pair[1]

                })

    return jsonify({

        "building":
            building,

        "building_name":
            building_names[
                building
            ],

        "floor":
            floor_num,

        "nodes": [

            {

                "name":
                    name,

                "x":
                    pos["x"],

                "y":
                    pos["y"],

                "type":
                    pos.get(
                        "type",
                        "node"
                    ),

                "room_number":
                    pos.get(
                        "room_number"
                    )

            }

            for name, pos
            in nodes_on_floor.items()

                ],

        "edges":
            edges

    })


# =========================================================
# CAMPUS LAYOUT
#
# A big, spread-out overview of how the blocks physically sit
# next to each other, mirroring the real PRP footprint:
#
#         E                       A
#         |                       |
#         D --------- M --------- B
#                      |
#                      F
#
# Positions are hand-placed (not generated) so the two long wings
# (E, A) read as wings and the smaller pods (D, B, M, F) read as
# pods, same as the campus_walkways graph already connects them.
# =========================================================

CAMPUS_CANVAS = {"width": 1000, "height": 900}

CAMPUS_LAYOUT = {
    "E": {"cx": 220, "cy": 180, "w": 220, "h": 320, "kind": "wing"},
    "A": {"cx": 780, "cy": 180, "w": 220, "h": 320, "kind": "wing"},
    "D": {"cx": 300, "cy": 455, "w": 170, "h": 170, "kind": "pod"},
    "B": {"cx": 700, "cy": 455, "w": 170, "h": 170, "kind": "pod"},
    "M": {"cx": 500, "cy": 620, "w": 160, "h": 150, "kind": "pod"},
    "F": {"cx": 500, "cy": 805, "w": 120, "h": 110, "kind": "pod"},
}


@app.route("/campus_layout")
def get_campus_layout():

    buildings = []

    for building in room_ranges:

        layout = CAMPUS_LAYOUT.get(building)

        if not layout:

            continue

        buildings.append({

            "id": building,

            "name": building_names[building],

            "cx": layout["cx"],

            "cy": layout["cy"],

            "w": layout["w"],

            "h": layout["h"],

            "kind": layout["kind"]

        })

    connections = [
        {"from": from_building, "to": to_building}
        for from_building, to_building, _distance in campus_walkways
    ]

    return jsonify({

        "canvas": CAMPUS_CANVAS,

        "buildings": buildings,

        "connections": connections

    })


# =========================================================
# BUILDINGS
# =========================================================

@app.route("/buildings")
def get_buildings():

    layout = {}

    for building in room_ranges:

        layout[building] = \
            sorted(
                room_ranges[
                    building
                ].keys()
        )

    return jsonify(
        layout
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        debug=True,
        port=5000
    )
