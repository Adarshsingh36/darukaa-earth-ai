from __future__ import annotations

import asyncio
import math
from typing import Any

import rasterio


CLASS_NAMES = {
    10: "tree_cover",
    20: "shrubland",
    30: "grassland",
    40: "cropland",
    50: "built_up",
    60: "bare_sparse_vegetation",
    70: "snow_ice",
    80: "permanent_water",
    90: "herbaceous_wetland",
    95: "mangroves",
    100: "moss_lichen",
}


WORLDCOVER_BASE = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
)


class WorldCoverService:
    """
    Point sampling from ESA WorldCover 2021 v200.

    WorldCover files are Cloud Optimized GeoTIFFs. Instead of
    downloading an entire 3° x 3° tile, GDAL/rasterio accesses
    the remote COG and retrieves only the raster blocks needed
    for the requested coordinate.
    """

    def __init__(
        self,
        timeout: float = 30.0,
    ):
        self.timeout = timeout

    @staticmethod
    def _tile_name(
        latitude: float,
        longitude: float,
    ) -> str:
        lat = math.floor(latitude / 3.0) * 3
        lon = math.floor(longitude / 3.0) * 3

        lat_prefix = "N" if lat >= 0 else "S"
        lon_prefix = "E" if lon >= 0 else "W"

        return (
            f"{lat_prefix}{abs(lat):02d}"
            f"{lon_prefix}{abs(lon):03d}"
        )

    @classmethod
    def _tile_url(
        cls,
        latitude: float,
        longitude: float,
    ) -> str:
        tile = cls._tile_name(
            latitude,
            longitude,
        )

        return (
            f"{WORLDCOVER_BASE}/v200/2021/map/"
            f"ESA_WorldCover_10m_2021_v200_"
            f"{tile}_Map.tif"
        )

    @staticmethod
    def _result(
        *,
        land_cover_class=None,
        land_cover_label=None,
        is_terrestrial=None,
        status="available",
        tile=None,
        error=None,
    ) -> dict[str, Any]:

        result = {
            "land_cover_class": land_cover_class,
            "land_cover_label": land_cover_label,
            "is_terrestrial": is_terrestrial,
            "land_cover_status": status,
            "source": "ESA WorldCover 2021 v200",
            "resolution_m": 10,
            "tile": tile,
        }

        if error:
            result["error"] = error

        return result

    @staticmethod
    def _sample_remote(
        url: str,
        latitude: float,
        longitude: float,
        tile: str,
    ) -> dict[str, Any]:

        try:
            with rasterio.open(
                "/vsicurl/" + url
            ) as dataset:

                row, col = dataset.index(
                    longitude,
                    latitude,
                )

                if (
                    row < 0
                    or row >= dataset.height
                    or col < 0
                    or col >= dataset.width
                ):
                    return WorldCoverService._result(
                        status="outside_tile",
                        tile=tile,
                    )

                value = int(
                    dataset.read(
                        1,
                        window=rasterio.windows.Window(
                            col,
                            row,
                            1,
                            1,
                        ),
                    )[0, 0]
                )

        except Exception as exc:
            message = str(exc)

            if "404" in message or "not exist" in message.lower():
                return WorldCoverService._result(
                    status="tile_not_available",
                    tile=tile,
                )

            return WorldCoverService._result(
                status="error",
                tile=tile,
                error=f"{type(exc).__name__}: {message}",
            )

        if value == 0:
            return WorldCoverService._result(
                status="pixel_nodata",
                tile=tile,
            )

        label = CLASS_NAMES.get(value)

        is_terrestrial = value not in {
            70,
            80,
        }

        return WorldCoverService._result(
            land_cover_class=value,
            land_cover_label=label,
            is_terrestrial=is_terrestrial,
            status="available",
            tile=tile,
        )

    async def fetch_land_cover(
        self,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:

        tile = self._tile_name(
            latitude,
            longitude,
        )

        url = self._tile_url(
            latitude,
            longitude,
        )

        # Rasterio/GDAL performs blocking I/O, so move the
        # remote COG read to a worker thread.
        result = await asyncio.to_thread(
            self._sample_remote,
            url,
            latitude,
            longitude,
            tile,
        )

        return result
