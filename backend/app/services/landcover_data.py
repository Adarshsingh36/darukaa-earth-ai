from __future__ import annotations

import io
import math
from typing import Any

import httpx
import rasterio


WORLDCOVER_BASE = (
    "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
)

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


class WorldCoverService:
    """Point sampling from ESA WorldCover 2021 v200."""

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout

    @staticmethod
    def _tile_name(
        latitude: float,
        longitude: float,
    ) -> str:

        # WorldCover tiles use the lower-left corner of each
        # 3-degree tile.
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

    async def fetch_land_cover(
        self,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:

        url = self._tile_url(
            latitude,
            longitude,
        )

        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
        ) as client:

            response = await client.get(url)

        if response.status_code != 200:
            raise RuntimeError(
                f"WorldCover HTTP {response.status_code}: "
                f"{url}"
            )

        content_type = response.headers.get(
            "content-type",
            "",
        )

        if (
            "tif" not in content_type.lower()
            and "octet-stream" not in content_type.lower()
        ):
            raise RuntimeError(
                "WorldCover did not return a GeoTIFF. "
                f"Content-Type={content_type}"
            )

        with rasterio.MemoryFile(
            io.BytesIO(response.content)
        ) as memfile:

            with memfile.open() as dataset:

                # WorldCover is EPSG:4326, so transform the
                # coordinate directly into the raster.
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
                    return {
                        "land_cover_class": None,
                        "land_cover_label": None,
                        "source": "ESA WorldCover 2021 v200",
                        "resolution_m": 10,
                        "tile": self._tile_name(
                            latitude,
                            longitude,
                        ),
                    }

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

        # WorldCover uses 0 as nodata.
        label = CLASS_NAMES.get(
            value
        )

        return {
            "land_cover_class": value
            if value != 0
            else None,

            "land_cover_label": label,

            "is_terrestrial": (
                value not in {
                    0,
                    70,
                    80,
                }
            ),

            "source": "ESA WorldCover 2021 v200",
            "resolution_m": 10,
            "tile": self._tile_name(
                latitude,
                longitude,
            ),
        }
