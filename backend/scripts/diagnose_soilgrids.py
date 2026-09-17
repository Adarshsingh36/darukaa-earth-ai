import asyncio
import io

import httpx
import numpy as np
import rasterio
from pyproj import CRS, Transformer


BASE = "https://maps.isric.org/mapserv"

PROJ4 = "+proj=igh +lat_0=0 +lon_0=0 +datum=WGS84 +units=m +no_defs"

crs = CRS.from_proj4(PROJ4)

transformer = Transformer.from_crs(
    "EPSG:4326",
    crs,
    always_xy=True,
)


async def main():

    latitude = 19.033
    longitude = 73.029

    x, y = transformer.transform(
        longitude,
        latitude,
    )

    print("WGS84:", longitude, latitude)
    print("Homolosine:", x, y)

    delta = 1000

    params = [
        ("map", "/map/soc.map"),
        ("SERVICE", "WCS"),
        ("VERSION", "2.0.1"),
        ("REQUEST", "GetCoverage"),
        ("COVERAGEID", "soc_0-5cm_Q0.5"),
        ("FORMAT", "GEOTIFF_INT16"),
        ("SUBSET", f"X({x-delta},{x+delta})"),
        ("SUBSET", f"Y({y-delta},{y+delta})"),
        (
            "SUBSETTINGCRS",
            "http://www.opengis.net/def/crs/EPSG/0/152160",
        ),
        (
            "OUTPUTCRS",
            "http://www.opengis.net/def/crs/EPSG/0/152160",
        ),
    ]

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(
            BASE,
            params=params,
        )

    print()
    print("HTTP:", response.status_code)
    print("Content-Type:", response.headers.get("content-type"))
    print("Bytes:", len(response.content))
    print("First bytes:", response.content[:20])

    with rasterio.MemoryFile(
        io.BytesIO(response.content)
    ) as mem:

        with mem.open() as ds:

            print()
            print("Raster driver:", ds.driver)
            print("Raster size:", ds.width, "x", ds.height)
            print("Bands:", ds.count)
            print("CRS:", ds.crs)
            print("Dtype:", ds.dtypes)
            print("NoData:", ds.nodata)
            print("Transform:", ds.transform)

            raw = ds.read(1)

            print()
            print("Raw min:", raw.min())
            print("Raw max:", raw.max())
            print("Raw mean:", raw.mean())
            print("Raw median:", np.median(raw))
            print("Unique sample:", np.unique(raw)[:30])

            masked = ds.read(
                1,
                masked=True,
            )

            valid = masked.compressed()

            print()
            print("Masked valid pixels:", len(valid))

            if len(valid):
                print("Valid min:", valid.min())
                print("Valid max:", valid.max())
                print("Valid mean:", valid.mean())
                print("Valid median:", np.median(valid))


asyncio.run(main())
