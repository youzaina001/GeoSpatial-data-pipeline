# GeoPipeline Pipeline Entry Point
"""Main entry point for local testing and development."""

from geopipeline.config import get_region_config, get_storage_config
from geopipeline.services import ingestion


def main():
    """Run a sample ingestion for testing."""
    print("GeoPipeline Geospatial Data Pipeline")
    print("=" * 40)

    # Show configuration
    region = get_region_config()
    print(f"Target Region: {region['name']}")
    print(f"Bounding Box: {region['bbox']}")
    print(f"Tile Size: {region['tile_size']} degrees")

    # Discover tiles for today
    from datetime import date
    today = date.today().isoformat()
    tiles = ingestion.discover_tiles_for_date(today)

    print(f"Discovered {len(tiles)} tiles for {today}:")
    for tile in tiles:
        print(f"-{tile['tile_id']}: bbox={tile['bbox']}, cloud={tile['cloud_coverage']:.1f}%")

    print("To run the full pipeline:")
    print("1. Start Minikube: ./scripts/start_minikube.sh")
    print("2. Deploy: ./scripts/deploy.sh")
    print("3. Access Airflow UI and trigger DAGs")


if __name__ == "__main__":
    main()
