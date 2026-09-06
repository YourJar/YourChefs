from flask import Flask, request, jsonify, send_from_directory
import heapq
import math
import os
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

    "B": {
        0: [(60, 67)],
        1: [(163, 171)],
        2: [(258, 266)],
        3: [(362, 370)],
        4: [(456, 463)],
        5: [(561, 567)],
        6: [(662, 669)],
        7: [(759, 765)],
    },

    "C": {
        0: [
            (1, 13),
            (14, 16),
            (17, 28),
        ],

        1: [
            (101, 114),
            (115, 118),
            (119, 131),
        ],

        2: [
            (201, 212),
            (213, 218),
            (219, 227),
        ],

        3: [
            (301, 311),
            (312, 315),
            (317, 326),
        ],

        4: [
            (401, 410),
            (411, 413),
            (414, 421),
        ],

        5: [
            (501, 511),
            (512, 517),
            (518, 526),
        ],

        6: [
            (601, 609),
            (611, 614),
            (615, 626),
        ],

        7: [
            (701, 713),
            (714, 715),
            (716, 728),
        ],
    },

    "D": {
        0: [(68, 72)],
        1: [(172, 176)],
        2: [(267, 275)],
        3: [(371, 379)],
        4: [(464, 472)],
        5: [(568, 576)],
        6: [(670, 678)],
        7: [(766, 773)],
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
    "C": "C Block",
    "D": "D Block",
    "E": "E Block",
}


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

def generate_room_positions(
    building,
    floor,
    room_numbers
):

    # One classroom occupies each side of a hexagon. Hexagons are
    # arranged in a grid: up to 3 per row, wrapping to a new row
    # below once a row is full - matching a real floor plan layout
    # rather than a single line or a ring.
    rooms_per_hexagon = 6

    hexagon_groups = [
        room_numbers[index:index + rooms_per_hexagon]
        for index in range(0, len(room_numbers), rooms_per_hexagon)
    ]

    max_per_row = 3

    num_groups = len(hexagon_groups)

    num_rows = math.ceil(num_groups / max_per_row)

    margin = 20

    # Reserve some space on the left for the staircase, which sits
    # outside the room grid rather than inside it.
    stairs_reserved_width = 60

    usable_width = 480 - 2 * margin - stairs_reserved_width

    usable_height = 340 - 2 * margin

    slot_width = usable_width / max_per_row

    slot_height = usable_height / num_rows

    grid_left = margin + stairs_reserved_width

    # 0.8 safety factor leaves a visible gap between hexagons, both
    # horizontally and vertically.
    hexagon_radius = min(
        52,
        (slot_width / 2 / 0.86) * 0.8,
        (slot_height / 2 / 0.75) * 0.8
    )

    side_positions = [
        (0.43, -0.75),
        (0.86, 0),
        (0.43, 0.75),
        (-0.43, 0.75),
        (-0.86, 0),
        (-0.43, -0.75),
    ]

    for group_index, group in enumerate(hexagon_groups):

        row = group_index // max_per_row

        col = group_index % max_per_row

        center_x = grid_left + slot_width / 2 + col * slot_width

        center_y = margin + slot_height / 2 + row * slot_height

        start_side = 0

        for index, room_number in enumerate(group):

            side_x, side_y = side_positions[
                (start_side + index) % 6
            ]

            x = center_x + hexagon_radius * side_x

            y = center_y + hexagon_radius * side_y

            node_name = (
                f"{building}-{room_number}"
            )

            positions[node_name] = {

                "x": x,

                "y": y,

                "floor": floor,

                "building": building,

                "type": "room",

                "room_number":
                    room_number

            }

    # Staircase sits just left of the grid, vertically centered
    # relative to the full grid height (not the map height), so it
    # lines up naturally next to whichever rooms are nearest it.
    grid_total_height = slot_height * num_rows

    stair_x = margin + stairs_reserved_width / 2

    stair_y = margin + grid_total_height / 2

    return stair_x, stair_y


# =========================================================
# CREATE ROOM POSITIONS
# =========================================================

stair_positions = {}

for building, floors in \
        rooms_by_floor.items():

    for floor, room_numbers in \
            floors.items():

        stair_x, stair_y = generate_room_positions(
            building,
            floor,
            room_numbers
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
            (240, 170)  # fallback for a floor with no room data
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

        "x": 20,

        "y": 285,

        "floor": 0,

        "building": building,

        "type": "entrance"

    }


# =========================================================
# CONNECT ROOMS
# =========================================================

for building, floors in \
        rooms_by_floor.items():

    for floor, room_numbers in \
            floors.items():

        # -------------------------------------------------
        # Connect rooms in sequence
        # -------------------------------------------------

        for i in range(
            len(room_numbers) - 1
        ):

            room1 = (
                f"{building}-{room_numbers[i]}"
            )

            room2 = (
                f"{building}-{room_numbers[i + 1]}"
            )

            add_edge(
                room1,
                room2,
                3,
                "follow the corridor"
            )

        # Close each six-room group into a hexagonal corridor loop.
        # The regular sequence edge between groups remains a clean
        # corridor connection, with no classroom in the middle.
        for room_group in (
            room_numbers[index:index + 6]
            for index in range(0, len(room_numbers), 6)
        ):

            if len(room_group) < 2:

                continue

            add_edge(
                f"{building}-{room_group[-1]}",
                f"{building}-{room_group[0]}",
                3,
                "continue around the hexagonal corridor"
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
# CONNECT BUILDINGS: U-SHAPED CAMPUS WALKWAY
#
# The coloured campus-map blocks form a U-shaped sequence:
# A -> B -> C -> D -> E.  Each outdoor edge joins the two
# building entrances, allowing a route to continue naturally
# from one block to the next.
# =========================================================

campus_walkways = [
    ("A", "B", 20),
    ("B", "C", 14),
    ("C", "D", 14),
    ("D", "E", 20),
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
# C101
# C-101
# C 101
#
# Bare numbers are supported.
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
    # C101 -> C-101
    # -----------------------------------------------------

    match = re.fullmatch(
        r"([A-E])[-]?(\d+)",
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
