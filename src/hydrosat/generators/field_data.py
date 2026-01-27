# Synthetic Field Data Generator
"""Generate synthetic agricultural field data with polygon geometries and planting dates."""

import hashlib
import random
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional


@dataclass
class Field:
    """Represents an agricultural field with geometry and planting information."""

    field_id: str
    name: str
    geometry: list[tuple[float, float]]  # Polygon coordinates [(lon, lat), ...]
    centroid: tuple[float, float]  # (lon, lat)
    area_hectares: float
    crop_type: str
    planting_date: str  # YYYY-MM-DD format

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Field":
        """Create Field from dictionary."""
        return cls(**data)


# Common crop types with typical planting windows
CROP_TYPES = [
    ("wheat", -60, -30),  # Planted 30-60 days before reference
    ("corn", -45, -15),  # Planted 15-45 days before reference
    ("soybean", -30, 0),  # Planted 0-30 days before reference
    ("sunflower", -20, 10),  # Planted -20 to +10 days from reference
]


def generate_field_id(lon: float, lat: float, index: int) -> str:
    """Generate a deterministic field ID based on location and index."""
    raw = f"field_{lon:.4f}_{lat:.4f}_{index}"
    return f"F{hashlib.md5(raw.encode()).hexdigest()[:8].upper()}"


def generate_polygon_around_point(
    center_lon: float,
    center_lat: float,
    size_deg: float = 0.02,
    irregularity: float = 0.3,
    seed: Optional[int] = None,
) -> list[tuple[float, float]]:
    """
    Generate an irregular polygon around a center point.

    Creates realistic field shapes that aren't perfect rectangles.

    Args:
        center_lon: Center longitude
        center_lat: Center latitude
        size_deg: Approximate size in degrees
        irregularity: How irregular the shape is (0-1)
        seed: Random seed for reproducibility

    Returns:
        List of (lon, lat) tuples forming a closed polygon
    """
    if seed is not None:
        random.seed(seed)

    # Generate 5-7 vertices for irregular polygon
    num_vertices = random.randint(5, 7)
    angles = sorted([random.uniform(0, 360) for _ in range(num_vertices)])

    vertices = []
    for angle in angles:
        # Vary the radius for irregularity
        radius = size_deg * (1 + random.uniform(-irregularity, irregularity))
        # Convert polar to cartesian
        import math

        rad = math.radians(angle)
        lon = center_lon + radius * math.cos(rad)
        lat = center_lat + radius * math.sin(rad) * 0.7  # Adjust for lat/lon ratio
        vertices.append((round(lon, 6), round(lat, 6)))

    # Close the polygon
    vertices.append(vertices[0])
    return vertices


def point_in_bbox(lon: float, lat: float, bbox: list[float]) -> bool:
    """Check if a point is inside a bounding box."""
    return bbox[0] <= lon <= bbox[2] and bbox[1] <= lat <= bbox[3]


def polygon_intersects_bbox(
    polygon: list[tuple[float, float]], bbox: list[float]
) -> bool:
    """
    Simple check if polygon intersects with bounding box.

    Uses centroid check + vertex check for simplicity.
    For production, use shapely.
    """
    # Check if any vertex is inside bbox
    for lon, lat in polygon:
        if point_in_bbox(lon, lat, bbox):
            return True

    # Check if bbox center is inside polygon (rough approximation)
    bbox_center = ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)
    return point_in_polygon(bbox_center[0], bbox_center[1], polygon)


def point_in_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    """Ray casting algorithm to check if point is in polygon."""
    n = len(polygon)
    inside = False

    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]

        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i

    return inside


def generate_planting_date(
    reference_date: str,
    crop_type: str,
    seed: Optional[int] = None,
) -> str:
    """
    Generate a planting date based on crop type.

    Different crops have different planting windows relative to reference date.
    """
    if seed is not None:
        random.seed(seed)

    ref = datetime.strptime(reference_date, "%Y-%m-%d")

    # Find crop planting window
    for crop, min_days, max_days in CROP_TYPES:
        if crop == crop_type:
            offset = random.randint(min_days, max_days)
            planting = ref + timedelta(days=offset)
            return planting.strftime("%Y-%m-%d")

    # Default: 30 days before reference
    return (ref - timedelta(days=30)).strftime("%Y-%m-%d")


def generate_fields_for_aoi(
    aoi_bbox: list[float],
    reference_date: str,
    num_fields: int = 6,
    seed: Optional[int] = None,
) -> list[Field]:
    """
    Generate synthetic fields that intersect with the AOI.

    Args:
        aoi_bbox: [lon_min, lat_min, lon_max, lat_max]
        reference_date: Reference date for planting date calculation
        num_fields: Number of fields to generate
        seed: Random seed for reproducibility

    Returns:
        List of Field objects
    """
    if seed is not None:
        random.seed(seed)

    fields = []

    # Calculate AOI dimensions
    lon_range = aoi_bbox[2] - aoi_bbox[0]
    lat_range = aoi_bbox[3] - aoi_bbox[1]

    for i in range(num_fields):
        # Generate field center within AOI (with some margin)
        margin = 0.1
        center_lon = random.uniform(
            aoi_bbox[0] + lon_range * margin,
            aoi_bbox[2] - lon_range * margin,
        )
        center_lat = random.uniform(
            aoi_bbox[1] + lat_range * margin,
            aoi_bbox[3] - lat_range * margin,
        )

        # Generate field properties
        field_seed = (seed + i * 1000) if seed else None
        field_id = generate_field_id(center_lon, center_lat, i)

        # Field size varies (0.01 to 0.04 degrees, roughly 1-4 km)
        field_size = random.uniform(0.01, 0.04)

        # Generate polygon
        geometry = generate_polygon_around_point(
            center_lon, center_lat, field_size, seed=field_seed
        )

        # Select crop type
        crop_type, _, _ = random.choice(CROP_TYPES)

        # Generate planting date
        planting_date = generate_planting_date(
            reference_date, crop_type, seed=field_seed
        )

        # Calculate approximate area (very rough)
        area_hectares = round(field_size * 111 * field_size * 111 * 0.7 * 100, 1)

        field = Field(
            field_id=field_id,
            name=f"{crop_type.capitalize()} Field {i + 1}",
            geometry=geometry,
            centroid=(round(center_lon, 6), round(center_lat, 6)),
            area_hectares=area_hectares,
            crop_type=crop_type,
            planting_date=planting_date,
        )
        fields.append(field)

    return fields


def get_eligible_fields(
    fields: list[Field],
    execution_date: str,
) -> list[Field]:
    """
    Filter fields to only those eligible for processing.

    A field is eligible if execution_date >= planting_date.

    Args:
        fields: List of all fields
        execution_date: Current processing date (YYYY-MM-DD)

    Returns:
        List of eligible fields
    """
    exec_dt = datetime.strptime(execution_date, "%Y-%m-%d")

    eligible = []
    for field in fields:
        planting_dt = datetime.strptime(field.planting_date, "%Y-%m-%d")
        if exec_dt >= planting_dt:
            eligible.append(field)

    return eligible
