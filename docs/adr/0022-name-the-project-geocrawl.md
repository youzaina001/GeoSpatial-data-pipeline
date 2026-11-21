# Name the project geocrawl

The repository started as a satellite pipeline called GeoPipeline and now measures crawl freshness ([ADR 0021](0021-archive-the-satellite-example.md)). The name follows the new direction: the Python package, the distribution and the CLI are all `geocrawl`. "Geo" records where the repository came from; it does not imply geospatial data.

The CLI drops the `crawl` group, because every command now concerns a crawl: `geocrawl build`, `geocrawl promote` and `geocrawl demo`. The crawl modules move from `geopipeline.crawl` to the package root (`geocrawl.extract`, `geocrawl.publish` and so on), and `make crawl-demo` becomes `make demo`, writing under `data/demo/`.

The published file formats ([ADR 0019](0019-manifest-and-comparison-contracts.md)) do not change. The GitHub repository is renamed by its owner; GitHub redirects the old `GeoSpatial-data-pipeline` URL.
