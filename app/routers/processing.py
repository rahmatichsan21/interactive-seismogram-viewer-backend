from fastapi import APIRouter

router = APIRouter(
    prefix="/api/process",
    tags=["Processing"]
)


@router.post("")
async def process():
    return {
        "status": "success",
        "message": "Processing endpoint is ready."
    }