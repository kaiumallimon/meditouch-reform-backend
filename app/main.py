from contextlib import asynccontextmanager
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, timezone
import uuid

from app.core.config import settings
from app.core.exceptions import AppException, app_exception_handler, unhandled_exception_handler
from app.core.middleware import RequestContextMiddleware
from app.core.logging import logger, setup_logging
from app.core.security import hash_password

# Initialize logging configuration
setup_logging(
    log_level=10 if settings.DEBUG else 20,
    log_dir="logs",
    json_format=(settings.ENVIRONMENT == "production")
)
from app.common.enums import UserRole
from app.db.mongodb import connect_to_mongo, close_mongo_connection, db_manager
from app.db.indexes import create_db_indexes
from app.integrations.medicine_source.medeasy_parser import ingest_medicine_catalog
from app.background.scheduler import background_scheduler_loop

# Module Routers
from app.modules.auth.router import router as auth_router
from app.modules.users.router import router as users_router
from app.modules.doctors.router import router as doctors_router
from app.modules.appointments.router import router as appointments_router
from app.modules.consultations.router import router as consultations_router
from app.modules.payments.router import router as payments_router
from app.modules.notifications.router import router as notifications_router
from app.modules.pharmacy.router import router as pharmacy_router
from app.modules.orders.router import router as orders_router
from app.modules.admin.router import router as admin_router
from app.modules.media.router import router as media_router
from app.modules.inventory.router import router as inventory_router
from app.modules.agent.router import router as agent_chat_router, admin_chat_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Startup
    logger.info("Initializing MediTouch Backend...")
    try:
        await connect_to_mongo()
        if db_manager.db is not None:
            await create_db_indexes(db_manager.db)

            # Seed default admin user if not exists
            admin_count = await db_manager.db.users.count_documents({"role": UserRole.ADMIN.value})
            if admin_count == 0:
                admin_user = {
                    "id": str(uuid.uuid4()),
                    "name": "Platform Administrator",
                    "phone": "+8801999999999",
                    "email": "kalimon291@gmail.com",
                    "hashed_password": hash_password("admin"),
                    "role": UserRole.ADMIN.value,
                    "is_active": True,
                    "created_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc)
                }
                await db_manager.db.users.insert_one(admin_user)
                logger.info("Seeded initial platform admin user")

        # Log SMTP Service status
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            logger.info(f"SMTP Email Service initialized: {settings.SMTP_HOST}:{settings.SMTP_PORT} ({settings.SMTP_FROM_EMAIL})")
        else:
            logger.info(f"SMTP running in Development/Mock mode (Credentials will be logged directly to console & logs)")
    except Exception as e:
        logger.warning(f"MongoDB warning during startup: {e}")

    scheduler_task = None
    if settings.ENVIRONMENT == "production":
        scheduler_task = asyncio.create_task(background_scheduler_loop())

    yield

    if scheduler_task:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass

    await close_mongo_connection()
    logger.info("MediTouch Backend shutdown complete.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="MediTouch Production Telemedicine and E-Pharmacy Backend API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan
)

app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = settings.API_V1_STR
app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(users_router, prefix=API_PREFIX)
app.include_router(doctors_router, prefix=API_PREFIX)
app.include_router(appointments_router, prefix=API_PREFIX)
app.include_router(consultations_router, prefix=API_PREFIX)
app.include_router(payments_router, prefix=API_PREFIX)
app.include_router(notifications_router, prefix=API_PREFIX)
app.include_router(pharmacy_router, prefix=API_PREFIX)
app.include_router(orders_router, prefix=API_PREFIX)
app.include_router(inventory_router, prefix=API_PREFIX)
app.include_router(admin_router, prefix=API_PREFIX)
app.include_router(media_router, prefix=API_PREFIX)
app.include_router(agent_chat_router, prefix=API_PREFIX)
app.include_router(admin_chat_router, prefix=API_PREFIX)

@app.get("/health", tags=["Health"])
@app.get(f"{API_PREFIX}/health", tags=["Health"])
async def health_check():
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
