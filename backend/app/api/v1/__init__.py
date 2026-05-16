from fastapi import APIRouter

from app.api.v1.endpoints import chat, ingest, search

router = APIRouter()
router.include_router(chat.router, prefix="/chat", tags=["chat"])
router.include_router(ingest.router, prefix="/ingest", tags=["ingest"])
router.include_router(search.router, prefix="/search", tags=["search"])
