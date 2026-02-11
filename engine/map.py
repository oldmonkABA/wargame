"""
Hex grid map system for India-Pakistan wargame simulation.

Uses axial coordinates (q, r) for hex grid with flat-top orientation.
Grid cell size: 10km
"""

import math
import yaml
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path


class TerrainType(Enum):
    MOUNTAIN = "mountain"
    HILLS = "hills"
    DESERT = "desert"
    PLAINS = "plains"
    URBAN = "urban"
    FOREST = "forest"
    MARSH = "marsh"
    RIVER = "river"


class Weather(Enum):
    CLEAR = "clear"
    CLOUDY = "cloudy"
    RAIN = "rain"
    STORM = "storm"
    FOG = "fog"
    SANDSTORM = "sandstorm"


class RoadType(Enum):
    NONE = "none"
    MINOR = "minor"
    MAJOR = "major"
    HIGHWAY = "highway"


@dataclass
class TerrainInfo:
    """Terrain type properties loaded from schema."""
    id: str
    name: str
    movement_cost: dict[str, float]  # by unit mobility type
    defense_bonus: float
    concealment: int  # 0-100
    air_ops: str  # "ideal", "normal", "restricted"
    los_blocking: bool | str  # True, False, or "partial"
    color: str


@dataclass
class HexCell:
    """Individual hex cell in the grid."""
    q: int  # axial coordinate
    r: int  # axial coordinate
    center_lat: float
    center_lon: float
    terrain: TerrainType
    elevation_m: int = 0
    features: list[str] = field(default_factory=list)
    location_id: Optional[str] = None  # city, airbase, etc.
    control: str = "neutral"  # "india", "pakistan", "contested", "neutral"
    fortification: int = 0  # 0-3
    road: RoadType = RoadType.NONE
    rail: bool = False
    unit_ids: list[str] = field(default_factory=list)

    @property
    def s(self) -> int:
        """Third cube coordinate (q + r + s = 0)."""
        return -self.q - self.r

    def cube_coords(self) -> tuple[int, int, int]:
        """Return cube coordinates (q, r, s)."""
        return (self.q, self.r, self.s)


@dataclass
class WeatherState:
    """Current weather conditions."""
    weather: Weather = Weather.CLEAR
    visibility_modifier: float = 1.0
    air_ops_modifier: float = 1.0
    movement_modifier: float = 1.0


class HexMap:
    """
    Hex grid map for the simulation.

    Uses axial coordinates with flat-top hexes.
    Origin is at map center, with positive q going east and positive r going southeast.
    """

    CELL_SIZE_KM = 10  # Each hex is 10km across

    def __init__(self, data_path: Path | str = "data"):
        self.data_path = Path(data_path)
        self.cells: dict[tuple[int, int], HexCell] = {}
        self.terrain_info: dict[str, TerrainInfo] = {}
        self.sectors: list[dict] = []
        self.rivers: list[dict] = []
        self.cities: list[dict] = []
        self.choke_points: list[dict] = []
        self.loc_path: list[dict] = []

        # Map bounds (lat/lon)
        self.north = 37.0
        self.south = 23.5
        self.east = 78.0
        self.west = 66.0

        # Grid dimensions calculated from bounds
        self.origin_lat = (self.north + self.south) / 2
        self.origin_lon = (self.east + self.west) / 2

        self.weather = WeatherState()
        self.is_night = False

        self._load_terrain_schema()
        self._load_terrain_data()
        self._generate_hex_grid()

    def _load_terrain_schema(self):
        """Load terrain type definitions from schema."""
        schema_path = self.data_path / "schema" / "map.yaml"
        if not schema_path.exists():
            self._create_default_terrain_info()
            return

        with open(schema_path) as f:
            schema = yaml.safe_load(f)

        for terrain_id, info in schema.get("terrain_types", {}).items():
            self.terrain_info[terrain_id] = TerrainInfo(
                id=info.get("id", terrain_id),
                name=info.get("name", terrain_id),
                movement_cost=info.get("movement_cost", {}),
                defense_bonus=info.get("defense_bonus", 1.0),
                concealment=info.get("concealment", 0),
                air_ops=info.get("air_ops", "normal"),
                los_blocking=info.get("los_blocking", False),
                color=info.get("color", "#888888")
            )

    def _create_default_terrain_info(self):
        """Create default terrain info if schema not found."""
        defaults = {
            "plains": (1.0, 1.0, 30),
            "hills": (2.0, 1.5, 60),
            "mountain": (4.0, 2.5, 80),
            "desert": (1.5, 0.8, 20),
            "urban": (2.0, 2.0, 70),
            "forest": (3.0, 1.6, 85),
            "marsh": (5.0, 1.3, 50),
            "river": (float('inf'), 0.5, 0),
        }
        for tid, (move, defense, conceal) in defaults.items():
            self.terrain_info[tid] = TerrainInfo(
                id=tid, name=tid.title(),
                movement_cost={"infantry": move, "mechanized": move * 1.5, "armor": move * 2},
                defense_bonus=defense, concealment=conceal,
                air_ops="normal", los_blocking=False, color="#888888"
            )

    def _load_terrain_data(self):
        """Load actual terrain/map data."""
        terrain_path = self.data_path / "map" / "terrain.yaml"
        if not terrain_path.exists():
            return

        with open(terrain_path) as f:
            data = yaml.safe_load(f)

        if "map_bounds" in data:
            bounds = data["map_bounds"]
            self.north = bounds.get("north", self.north)
            self.south = bounds.get("south", self.south)
            self.east = bounds.get("east", self.east)
            self.west = bounds.get("west", self.west)
            self.origin_lat = (self.north + self.south) / 2
            self.origin_lon = (self.east + self.west) / 2

        self.sectors = data.get("sectors", [])
        self.rivers = data.get("rivers", [])
        self.cities = data.get("major_cities", [])
        self.choke_points = data.get("choke_points", [])
        self.loc_path = data.get("loc", {}).get("approximate_path", [])

    def _generate_hex_grid(self):
        """Generate hex grid covering the map bounds."""
        # Calculate grid dimensions
        lat_range_km = (self.north - self.south) * 111  # ~111km per degree lat
        lon_range_km = (self.east - self.west) * 111 * math.cos(math.radians(self.origin_lat))

        # Hex dimensions for flat-top
        hex_width = self.CELL_SIZE_KM
        hex_height = hex_width * math.sqrt(3) / 2

        # Calculate q and r ranges
        q_range = int(lon_range_km / (hex_width * 0.75)) + 2
        r_range = int(lat_range_km / hex_height) + 2

        # Generate hexes
        for q in range(-q_range // 2, q_range // 2 + 1):
            for r in range(-r_range // 2, r_range // 2 + 1):
                lat, lon = self.hex_to_latlon(q, r)

                # Skip if outside bounds
                if not (self.south <= lat <= self.north and self.west <= lon <= self.east):
                    continue

                terrain = self._get_terrain_for_location(lat, lon)
                elevation = self._get_elevation_for_location(lat, lon)
                control = self._get_initial_control(lat, lon)

                self.cells[(q, r)] = HexCell(
                    q=q, r=r,
                    center_lat=lat, center_lon=lon,
                    terrain=terrain,
                    elevation_m=elevation,
                    control=control
                )

    def _get_terrain_for_location(self, lat: float, lon: float) -> TerrainType:
        """Determine terrain type for a lat/lon based on sectors."""
        for sector in self.sectors:
            bounds = sector.get("bounds", {})
            if (bounds.get("south", -90) <= lat <= bounds.get("north", 90) and
                bounds.get("west", -180) <= lon <= bounds.get("east", 180)):
                primary = sector.get("terrain_primary", "plains")
                try:
                    return TerrainType(primary)
                except ValueError:
                    return TerrainType.PLAINS
        return TerrainType.PLAINS

    def _get_elevation_for_location(self, lat: float, lon: float) -> int:
        """Get approximate elevation for a location."""
        for sector in self.sectors:
            bounds = sector.get("bounds", {})
            if (bounds.get("south", -90) <= lat <= bounds.get("north", 90) and
                bounds.get("west", -180) <= lon <= bounds.get("east", 180)):
                elev_range = sector.get("elevation_range", {})
                return (elev_range.get("min", 200) + elev_range.get("max", 200)) // 2
        return 200

    def _get_initial_control(self, lat: float, lon: float) -> str:
        """Determine initial territorial control."""
        # Simplified: use longitude relative to approximate border
        # Real implementation would use actual border data
        if lon < 74.0:
            return "pakistan"
        elif lon > 75.5:
            return "india"
        else:
            return "contested"

    # Hex coordinate conversions
    def hex_to_latlon(self, q: int, r: int) -> tuple[float, float]:
        """Convert hex coordinates to lat/lon."""
        # Flat-top hex: x = size * 3/2 * q, y = size * sqrt(3) * (r + q/2)
        hex_width_deg = self.CELL_SIZE_KM / (111 * math.cos(math.radians(self.origin_lat)))
        hex_height_deg = self.CELL_SIZE_KM / 111

        lon = self.origin_lon + hex_width_deg * 0.75 * q
        lat = self.origin_lat - hex_height_deg * math.sqrt(3) / 2 * (r + q / 2)

        return (lat, lon)

    def latlon_to_hex(self, lat: float, lon: float) -> tuple[int, int]:
        """Convert lat/lon to hex coordinates."""
        hex_width_deg = self.CELL_SIZE_KM / (111 * math.cos(math.radians(self.origin_lat)))
        hex_height_deg = self.CELL_SIZE_KM / 111

        q = (lon - self.origin_lon) / (hex_width_deg * 0.75)
        r = (self.origin_lat - lat) / (hex_height_deg * math.sqrt(3) / 2) - q / 2

        return self._round_hex(q, r)

    def _round_hex(self, q: float, r: float) -> tuple[int, int]:
        """Round fractional hex coordinates to nearest hex."""
        s = -q - r
        rq, rr, rs = round(q), round(r), round(s)

        q_diff = abs(rq - q)
        r_diff = abs(rr - r)
        s_diff = abs(rs - s)

        if q_diff > r_diff and q_diff > s_diff:
            rq = -rr - rs
        elif r_diff > s_diff:
            rr = -rq - rs

        return (int(rq), int(rr))

    # Hex operations
    def get_cell(self, q: int, r: int) -> Optional[HexCell]:
        """Get cell at coordinates."""
        return self.cells.get((q, r))

    def get_cell_at_latlon(self, lat: float, lon: float) -> Optional[HexCell]:
        """Get cell containing lat/lon point."""
        q, r = self.latlon_to_hex(lat, lon)
        return self.get_cell(q, r)

    def get_neighbors(self, q: int, r: int) -> list[HexCell]:
        """Get all adjacent hex cells."""
        # Axial direction vectors for flat-top hexes
        directions = [(1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1)]
        neighbors = []
        for dq, dr in directions:
            cell = self.get_cell(q + dq, r + dr)
            if cell:
                neighbors.append(cell)
        return neighbors

    def hex_distance(self, q1: int, r1: int, q2: int, r2: int) -> int:
        """Calculate distance in hexes between two cells."""
        return (abs(q1 - q2) + abs(q1 + r1 - q2 - r2) + abs(r1 - r2)) // 2

    def distance_km(self, q1: int, r1: int, q2: int, r2: int) -> float:
        """Calculate approximate distance in km."""
        return self.hex_distance(q1, r1, q2, r2) * self.CELL_SIZE_KM

    # Movement and combat support
    def get_movement_cost(self, cell: HexCell, mobility_type: str) -> float:
        """Get movement cost for a unit type entering this cell."""
        terrain_id = cell.terrain.value
        info = self.terrain_info.get(terrain_id)
        if not info:
            return 1.0

        base_cost = info.movement_cost.get(mobility_type,
                    info.movement_cost.get("infantry", 1.0))

        # Road bonus
        if cell.road == RoadType.HIGHWAY:
            base_cost *= 0.5
        elif cell.road == RoadType.MAJOR:
            base_cost *= 0.7
        elif cell.road == RoadType.MINOR:
            base_cost *= 0.85

        # Weather modifier
        base_cost *= (1.0 / self.weather.movement_modifier)

        return base_cost

    def get_defense_modifier(self, cell: HexCell) -> float:
        """Get defense modifier for units in this cell."""
        terrain_id = cell.terrain.value
        info = self.terrain_info.get(terrain_id)
        base_defense = info.defense_bonus if info else 1.0

        # Fortification bonus (15% per level)
        fort_bonus = 1.0 + (cell.fortification * 0.15)

        return base_defense * fort_bonus

    def get_concealment(self, cell: HexCell) -> int:
        """Get concealment value for this cell (0-100)."""
        terrain_id = cell.terrain.value
        info = self.terrain_info.get(terrain_id)
        base = info.concealment if info else 30

        # Weather effects
        if self.weather.weather in (Weather.FOG, Weather.STORM, Weather.SANDSTORM):
            base = min(100, base + 30)
        elif self.weather.weather == Weather.RAIN:
            base = min(100, base + 15)

        # Night bonus
        if self.is_night:
            base = min(100, base + 25)

        return base

    # Line of sight
    def has_line_of_sight(self, from_cell: HexCell, to_cell: HexCell) -> bool:
        """Check if there's line of sight between two cells."""
        path = self._get_hex_line(from_cell.q, from_cell.r, to_cell.q, to_cell.r)

        for q, r in path[1:-1]:  # Exclude start and end
            cell = self.get_cell(q, r)
            if not cell:
                continue

            info = self.terrain_info.get(cell.terrain.value)
            if info and info.los_blocking is True:
                # Check elevation - higher observer can see over
                if from_cell.elevation_m <= cell.elevation_m:
                    return False

        return True

    def _get_hex_line(self, q1: int, r1: int, q2: int, r2: int) -> list[tuple[int, int]]:
        """Get all hexes along a line between two points."""
        n = self.hex_distance(q1, r1, q2, r2)
        if n == 0:
            return [(q1, r1)]

        results = []
        for i in range(n + 1):
            t = i / n
            q = q1 + (q2 - q1) * t
            r = r1 + (r2 - r1) * t
            results.append(self._round_hex(q, r))

        return results

    # Pathfinding
    def find_path(self, start: tuple[int, int], end: tuple[int, int],
                  mobility_type: str, max_cost: float = float('inf')) -> list[tuple[int, int]]:
        """Find optimal path using A* algorithm."""
        import heapq

        if start == end:
            return [start]

        open_set = [(0, start)]
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        g_score = {start: 0.0}

        while open_set:
            _, current = heapq.heappop(open_set)

            if current == end:
                # Reconstruct path
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                return list(reversed(path))

            cell = self.get_cell(*current)
            if not cell:
                continue

            for neighbor in self.get_neighbors(*current):
                neighbor_pos = (neighbor.q, neighbor.r)
                move_cost = self.get_movement_cost(neighbor, mobility_type)

                # Impassable
                if move_cost == float('inf'):
                    continue

                tentative_g = g_score[current] + move_cost

                if tentative_g > max_cost:
                    continue

                if neighbor_pos not in g_score or tentative_g < g_score[neighbor_pos]:
                    came_from[neighbor_pos] = current
                    g_score[neighbor_pos] = tentative_g
                    f_score = tentative_g + self.hex_distance(*neighbor_pos, *end)
                    heapq.heappush(open_set, (f_score, neighbor_pos))

        return []  # No path found

    # Weather and time
    def set_weather(self, weather: Weather):
        """Set current weather conditions."""
        self.weather.weather = weather

        weather_effects = {
            Weather.CLEAR: (1.0, 1.0, 1.0),
            Weather.CLOUDY: (0.8, 0.9, 1.0),
            Weather.RAIN: (0.5, 0.5, 0.8),
            Weather.STORM: (0.2, 0.1, 0.5),
            Weather.FOG: (0.1, 0.2, 0.9),
            Weather.SANDSTORM: (0.1, 0.1, 0.6),
        }

        vis, air, move = weather_effects.get(weather, (1.0, 1.0, 1.0))
        self.weather.visibility_modifier = vis
        self.weather.air_ops_modifier = air
        self.weather.movement_modifier = move

    def set_time_of_day(self, is_night: bool):
        """Set day/night state."""
        self.is_night = is_night
        if is_night:
            self.weather.visibility_modifier *= 0.3
            self.weather.air_ops_modifier *= 0.7

    # Utility
    def get_cells_in_radius(self, q: int, r: int, radius: int) -> list[HexCell]:
        """Get all cells within radius hexes of center."""
        cells = []
        for dq in range(-radius, radius + 1):
            for dr in range(max(-radius, -dq - radius), min(radius, -dq + radius) + 1):
                cell = self.get_cell(q + dq, r + dr)
                if cell:
                    cells.append(cell)
        return cells

    def get_cells_by_control(self, faction: str) -> list[HexCell]:
        """Get all cells controlled by a faction."""
        return [c for c in self.cells.values() if c.control == faction]

    def get_stats(self) -> dict:
        """Get map statistics."""
        terrain_counts = {}
        control_counts = {"india": 0, "pakistan": 0, "contested": 0, "neutral": 0}

        for cell in self.cells.values():
            terrain = cell.terrain.value
            terrain_counts[terrain] = terrain_counts.get(terrain, 0) + 1
            control_counts[cell.control] = control_counts.get(cell.control, 0) + 1

        return {
            "total_cells": len(self.cells),
            "terrain_distribution": terrain_counts,
            "control_distribution": control_counts,
            "map_area_km2": len(self.cells) * (self.CELL_SIZE_KM ** 2) * 0.866,  # hex area
        }
