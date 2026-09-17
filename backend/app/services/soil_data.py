from __future__ import annotations

import io
import math
from typing import Any

import httpx
import rasterio
from pyproj import CRS, Transformer


SOILGRIDS_BASE = "https://maps.isric.org/mapserv"

SOILGRIDS_PROJ4 = (
    "+proj=igh "
    "+lat_0=0 "
    "+lon_0=0 "
    "+datum=WGS84 "
    "+units=m "
    "+no_defs"
)

SOILGRIDS_CRS = CRS.from_proj4(SOILGRIDS_PROJ4)

TRANSFORMER = Transformer.from_crs(
    "EPSG:4326",
    SOILGRIDS_CRS,
    always_xy=True,
)


class SoilGridsService:
    """Retrieve point-level SoilGrids predictions safely."""

    def __init__(self, timeout: float = 60.0):
        self.timeout = timeout

    async def _get_point(
        self,
        property_name: str,
        coverage_id: str,
        latitude: float,
        longitude: float,
    ) -> tuple[float | None, float | None]:

        x, y = TRANSFORMER.transform(
            longitude,
            latitude,
        )

        # 2 km × 2 km window.
        # This gives us nearby 250 m cells if the exact point
        # happens to have no usable soil prediction.
        delta = 1000.0

        params = [
            ("map", f"/map/{property_name}.map"),
            ("SERVICE", "WCS"),
            ("VERSION", "2.0.1"),
            ("REQUEST", "GetCoverage"),
            ("COVERAGEID", coverage_id),
            ("FORMAT", "GEOTIFF_INT16"),
            ("SUBSET", f"X({x - delta},{x + delta})"),
            ("SUBSET", f"Y({y - delta},{y + delta})"),
            (
                "SUBSETTINGCRS",
                "http://www.opengis.net/def/crs/EPSG/0/152160",
            ),
            (
                "OUTPUTCRS",
                "http://www.opengis.net/def/crs/EPSG/0/152160",
            ),
        ]

        async with httpx.AsyncClient(
            timeout=self.timeout
        ) as client:
            response = await client.get(
                SOILGRIDS_BASE,
                params=params,
            )

        content_type = response.headers.get(
            "content-type",
            "",
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"SoilGrids HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        if (
            "tiff" not in content_type.lower()
            and "octet-stream" not in content_type.lower()
        ):
            raise RuntimeError(
                "SoilGrids did not return GeoTIFF. "
                f"Content-Type={content_type}; "
                f"Response={response.text[:500]}"
            )

        with rasterio.MemoryFile(
            io.BytesIO(response.content)
        ) as memfile:

            with memfile.open() as dataset:

                row, col = dataset.index(x, y)

                if (
                    row < 0
                    or row >= dataset.height
                    or col < 0
                    or col >= dataset.width
                ):
                    return None, None

                values = dataset.read(1)

                # SoilGrids integer products can contain zero values
                # where no usable prediction is available. For SOC and
                # pH, zero is not a scientifically meaningful value.
                exact_value = float(values[row, col])

                if exact_value > 0:
                    return exact_value, 0.0

                # Exact cell unavailable.
                # Find the nearest positive cell as a documented fallback.
                candidates = []

                for r in range(dataset.height):
                    for c in range(dataset.width):

                        value = float(values[r, c])

                        if value <= 0:
                            continue

                        px, py = dataset.xy(
                            r,
                            c,
                        )

                        distance = math.sqrt(
                            (px - x) ** 2
                            + (py - y) ** 2
                        )

                        candidates.append(
                            (
                                distance,
                                value,
                            )
                        )

                if not candidates:
                    return None, None

                distance, value = min(
                    candidates,
                    key=lambda item: item[0],
                )

                return value, round(distance, 1)

    async def fetch_soil(
        self,
        latitude: float,
        longitude: float,
    ) -> dict[str, Any]:

        soc_raw, soc_distance = await self._get_point(
            "soc",
            "soc_0-5cm_Q0.5",
            latitude,
            longitude,
        )

        ph_raw, ph_distance = await self._get_point(
            "phh2o",
            "phh2o_0-5cm_Q0.5",
            latitude,
            longitude,
        )

        soc_g_per_kg = (
            round(soc_raw / 10.0, 3)
            if soc_raw is not None
            else None
        )

        ph = (
            round(ph_raw / 10.0, 2)
            if ph_raw is not None
            else None
        )

        return {
            "soil_organic_carbon_g_per_kg": soc_g_per_kg,
            "soil_ph": ph,
            "soil_depth": "0-5cm",

            "soc_source_distance_m": soc_distance,
            "ph_source_distance_m": ph_distance,

            "source": "ISRIC SoilGrids",
            "resolution_m": 250,

            "crs": (
                "SoilGrids Homolosine / pseudo-EPSG:152160"
            ),
        }
