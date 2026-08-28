from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from typing import Optional
from app.core.config import settings
from app.core.logging import logger

class MongoDBManager:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None

db_manager = MongoDBManager()

async def connect_to_mongo():
    logger.info("Connecting to MongoDB...")
    db_manager.client = AsyncIOMotorClient(
        settings.MONGODB_URL,
        maxPoolSize=50,
        minPoolSize=10,
        serverSelectionTimeoutMS=5000
    )
    db_manager.db = db_manager.client[settings.MONGODB_DB_NAME]
    logger.info(f"Connected to MongoDB database: {settings.MONGODB_DB_NAME}")

async def close_mongo_connection():
    logger.info("Closing MongoDB connection...")
    if db_manager.client:
        db_manager.client.close()
        logger.info("MongoDB connection closed.")

def get_database() -> AsyncIOMotorDatabase:
    if db_manager.db is None:
        raise RuntimeError("Database is not initialized. Ensure connect_to_mongo() has run.")
    return db_manager.db

async def get_db() -> AsyncIOMotorDatabase:
    return get_database()
