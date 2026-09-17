from fastapi import APIRouter, HTTPException

from app.models.environment import LocationRequest, LocationResponse
from app.services.environment_data import EnvironmentalDataService


router = APIRouter(prefix="/environment", tags=["environment"])
service = EnvironmentalDataService()


@router.post("/location", response_model=LocationResponse)
async def enrich_location(req: LocationRequest):
    try:
        return await service.enrich_location(
            req.latitude,
            req.longitude,
            req.radius_km,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Environmental data acquisition failed: {exc}",
        ) from exc
