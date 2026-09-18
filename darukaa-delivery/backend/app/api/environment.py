from fastapi import APIRouter, HTTPException

from app.models.environment import LocationRequest, LocationResponse
from app.services.environment_data import EnvironmentalDataService


router = APIRouter(prefix="/environment", tags=["environment"])
service = EnvironmentalDataService()


@router.post("/location", response_model=LocationResponse)
async def enrich_location(req: LocationRequest):
    """
    Live environmental context for a point.

    A partial result is a success, not an error. The previous version
    wrapped the whole call in try/except and returned 502 on any
    failure, so one slow GBIF query lost the NASA POWER and SoilGrids
    data that had already arrived. Failures are now reported per source
    in `degraded_sources`, and only a total failure is an error.
    """
    try:
        result = await service.enrich_location(
            req.latitude,
            req.longitude,
            req.radius_km,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Environmental data acquisition failed: {exc}",
        ) from exc

    if not result["data_sources"]:
        raise HTTPException(
            status_code=502,
            detail={
                "message": (
                    "No environmental data source was reachable for "
                    "this location."
                ),
                "degraded_sources": result["degraded_sources"],
            },
        )

    return result
