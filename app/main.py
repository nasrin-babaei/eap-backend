import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.core.config import settings

from app.api.routes.auth import router as auth_router
from app.api.routes.rbac import router as rbac_router
from app.api.routes.requests import router as requests_router
from app.api.routes.approver import router as approver_router
from app.api.routes.admin import router as admin_router
from app.api.routes.reports import router as reports_router
from app.api.routes import audit_log
from app.api.routes.notifications import router as notifications_router
from app.api.routes.request_types import router as request_types_router
from app.api.routes.request_types import admin_router as request_types_admin_router
app = FastAPI(
    title="EAP API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    """
    EAP-IT35 — Return a user-friendly message instead of slowapi's
    default raw limit string (e.g. "5 per 1 minute").
    """
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many login attempts. Please wait a minute and try again."},
    )


# Routers
app.include_router(auth_router, prefix="/api")
app.include_router(rbac_router, prefix="/api")
app.include_router(requests_router, prefix="/api")
app.include_router(approver_router, prefix="/api")
app.include_router(admin_router, prefix="/api")
app.include_router(reports_router, prefix="/api")
app.include_router(audit_log.router,prefix="/api")
app.include_router(notifications_router, prefix="/api")
# US-017 — the public list and the admin management endpoints are two routers
# from the same file (see app/api/routes/request_types.py).
app.include_router(request_types_router, prefix="/api")
app.include_router(request_types_admin_router, prefix="/api")


@app.get("/health")
def health_check():
    return {"status": "ok"}
