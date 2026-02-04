# Tests for Field Data Generator
"""Tests for geopipeline.generators.field_data module."""

from datetime import datetime

from geopipeline.generators.field_data import (
    Field,
    generate_field_id,
    generate_polygon_around_point,
    generate_planting_date,
    generate_fields_for_aoi,
    get_eligible_fields,
    point_in_polygon,
)


class TestField:
    """Tests for Field dataclass."""

    def test_field_to_dict(self):
        """Test Field serialization."""
        field = Field(
            field_id="F12345678",
            name="Test Field",
            geometry=[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
            centroid=(0.5, 0.5),
            area_hectares=100.0,
            crop_type="wheat",
            planting_date="2024-03-15",
        )
        data = field.to_dict()

        assert data["field_id"] == "F12345678"
        assert data["crop_type"] == "wheat"
        assert data["planting_date"] == "2024-03-15"

    def test_field_from_dict(self):
        """Test Field deserialization."""
        data = {
            "field_id": "F12345678",
            "name": "Test Field",
            "geometry": [(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)],
            "centroid": (0.5, 0.5),
            "area_hectares": 100.0,
            "crop_type": "corn",
            "planting_date": "2024-04-01",
        }
        field = Field.from_dict(data)

        assert field.field_id == "F12345678"
        assert field.crop_type == "corn"


class TestGenerateFieldId:
    """Tests for field ID generation."""

    def test_deterministic(self):
        """Field ID should be deterministic for same inputs."""
        id1 = generate_field_id(2.5, 48.5, 0)
        id2 = generate_field_id(2.5, 48.5, 0)
        assert id1 == id2

    def test_different_for_different_location(self):
        """Field ID should differ for different locations."""
        id1 = generate_field_id(2.5, 48.5, 0)
        id2 = generate_field_id(2.6, 48.5, 0)
        assert id1 != id2

    def test_different_for_different_index(self):
        """Field ID should differ for different indices."""
        id1 = generate_field_id(2.5, 48.5, 0)
        id2 = generate_field_id(2.5, 48.5, 1)
        assert id1 != id2

    def test_starts_with_f(self):
        """Field ID should start with 'F'."""
        field_id = generate_field_id(2.5, 48.5, 0)
        assert field_id.startswith("F")


class TestGeneratePolygon:
    """Tests for polygon generation."""

    def test_creates_closed_polygon(self):
        """Polygon should be closed (first == last vertex)."""
        polygon = generate_polygon_around_point(2.5, 48.5, seed=42)
        assert polygon[0] == polygon[-1]

    def test_has_minimum_vertices(self):
        """Polygon should have at least 5 vertices (closed)."""
        polygon = generate_polygon_around_point(2.5, 48.5, seed=42)
        assert len(polygon) >= 6  # 5+ vertices + closing vertex

    def test_reproducible_with_seed(self):
        """Polygon should be reproducible with same seed."""
        p1 = generate_polygon_around_point(2.5, 48.5, seed=42)
        p2 = generate_polygon_around_point(2.5, 48.5, seed=42)
        assert p1 == p2


class TestGeneratePlantingDate:
    """Tests for planting date generation."""

    def test_returns_valid_date_format(self):
        """Planting date should be in YYYY-MM-DD format."""
        date = generate_planting_date("2024-06-01", "wheat", seed=42)
        # Should parse without error
        datetime.strptime(date, "%Y-%m-%d")

    def test_reproducible_with_seed(self):
        """Planting date should be reproducible with same seed."""
        d1 = generate_planting_date("2024-06-01", "wheat", seed=42)
        d2 = generate_planting_date("2024-06-01", "wheat", seed=42)
        assert d1 == d2

    def test_different_crops_may_have_different_dates(self):
        """Different crop types may have different planting windows."""
        wheat_date = generate_planting_date("2024-06-01", "wheat", seed=42)
        corn_date = generate_planting_date("2024-06-01", "corn", seed=42)
        # They might be different (depends on random within window)
        # Just verify both are valid dates
        datetime.strptime(wheat_date, "%Y-%m-%d")
        datetime.strptime(corn_date, "%Y-%m-%d")


class TestGenerateFieldsForAoi:
    """Tests for field generation within AOI."""

    def test_generates_requested_number_of_fields(self):
        """Should generate the requested number of fields."""
        aoi_bbox = [2.0, 48.0, 3.0, 49.0]
        fields = generate_fields_for_aoi(aoi_bbox, "2024-06-01", num_fields=5, seed=42)
        assert len(fields) == 5

    def test_fields_have_required_attributes(self):
        """Each field should have all required attributes."""
        aoi_bbox = [2.0, 48.0, 3.0, 49.0]
        fields = generate_fields_for_aoi(aoi_bbox, "2024-06-01", num_fields=3, seed=42)

        for field in fields:
            assert hasattr(field, "field_id")
            assert hasattr(field, "name")
            assert hasattr(field, "geometry")
            assert hasattr(field, "centroid")
            assert hasattr(field, "crop_type")
            assert hasattr(field, "planting_date")

    def test_reproducible_with_seed(self):
        """Field generation should be reproducible with same seed."""
        aoi_bbox = [2.0, 48.0, 3.0, 49.0]
        fields1 = generate_fields_for_aoi(aoi_bbox, "2024-06-01", num_fields=3, seed=42)
        fields2 = generate_fields_for_aoi(aoi_bbox, "2024-06-01", num_fields=3, seed=42)

        assert len(fields1) == len(fields2)
        for f1, f2 in zip(fields1, fields2):
            assert f1.field_id == f2.field_id
            assert f1.crop_type == f2.crop_type


class TestGetEligibleFields:
    """Tests for field eligibility filtering."""

    def test_filters_by_planting_date(self):
        """Should only return fields with planting_date <= execution_date."""
        fields = [
            Field("F1", "Field 1", [], (0, 0), 100, "wheat", "2024-03-01"),
            Field("F2", "Field 2", [], (0, 0), 100, "corn", "2024-04-01"),
            Field("F3", "Field 3", [], (0, 0), 100, "soybean", "2024-05-01"),
        ]

        # On April 15, only F1 and F2 should be eligible
        eligible = get_eligible_fields(fields, "2024-04-15")

        assert len(eligible) == 2
        assert any(f.field_id == "F1" for f in eligible)
        assert any(f.field_id == "F2" for f in eligible)
        assert not any(f.field_id == "F3" for f in eligible)

    def test_includes_field_on_planting_date(self):
        """Field should be eligible on its planting date."""
        fields = [
            Field("F1", "Field 1", [], (0, 0), 100, "wheat", "2024-04-01"),
        ]

        eligible = get_eligible_fields(fields, "2024-04-01")
        assert len(eligible) == 1

    def test_empty_list_if_none_eligible(self):
        """Should return empty list if no fields are eligible."""
        fields = [
            Field("F1", "Field 1", [], (0, 0), 100, "wheat", "2024-06-01"),
        ]

        eligible = get_eligible_fields(fields, "2024-04-01")
        assert len(eligible) == 0


class TestPointInPolygon:
    """Tests for point-in-polygon algorithm."""

    def test_point_inside(self):
        """Point inside polygon should return True."""
        polygon = [(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]
        assert point_in_polygon(1, 1, polygon) is True

    def test_point_outside(self):
        """Point outside polygon should return False."""
        polygon = [(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]
        assert point_in_polygon(3, 3, polygon) is False
