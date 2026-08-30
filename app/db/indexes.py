from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, TEXT, IndexModel
from app.core.logging import logger

async def create_db_indexes(db: AsyncIOMotorDatabase) -> None:
    try:
        logger.info("Creating MongoDB indexes...")
        await db.users.create_indexes([
            IndexModel([("email", ASCENDING)], unique=True, sparse=True, name="idx_users_email_unique"),
            IndexModel([("phone", ASCENDING)], unique=True, name="idx_users_phone_unique"),
            IndexModel([("role", ASCENDING)], name="idx_users_role"),
        ])
        await db.doctors.create_indexes([
            IndexModel([("user_id", ASCENDING)], unique=True, name="idx_doctors_user_id_unique"),
            IndexModel([("bmdc_reg_number", ASCENDING)], unique=True, name="idx_doctors_bmdc_unique"),
            IndexModel([("is_verified", ASCENDING)], name="idx_doctors_is_verified"),
            IndexModel([("is_active", ASCENDING)], name="idx_doctors_is_active"),
            IndexModel([("specialties", ASCENDING)], name="idx_doctors_specialties"),
            IndexModel([("consultation_fee", ASCENDING)], name="idx_doctors_fee"),
        ])
        await db.timeslots.create_indexes([
            IndexModel([("doctor_id", ASCENDING), ("start_time", ASCENDING)], unique=True, name="idx_timeslots_doc_time_unique"),
            IndexModel([("status", ASCENDING)], name="idx_timeslots_status"),
            IndexModel([("start_time", ASCENDING)], name="idx_timeslots_start_time"),
            IndexModel([("doctor_id", ASCENDING), ("status", ASCENDING)], name="idx_timeslots_doc_status"),
        ])
        await db.appointments.create_indexes([
            IndexModel([("patient_id", ASCENDING)], name="idx_appointments_patient"),
            IndexModel([("doctor_id", ASCENDING)], name="idx_appointments_doctor"),
            IndexModel([("timeslot_id", ASCENDING)], name="idx_appointments_timeslot"),
            IndexModel([("status", ASCENDING)], name="idx_appointments_status"),
            IndexModel([("payment_id", ASCENDING)], name="idx_appointments_payment"),
            IndexModel([("start_time", ASCENDING)], name="idx_appointments_start_time"),
        ])
        try:
            await db.medicines.create_indexes([
                IndexModel([("slug", ASCENDING)], unique=True, sparse=True, name="idx_medicines_slug_unique"),
                IndexModel(
                    [("name", TEXT), ("generic_name", TEXT), ("brand", TEXT), ("manufacturer", TEXT), ("medicine_name", TEXT)],
                    name="idx_medicines_text_search"
                ),
                IndexModel([("category", ASCENDING)], name="idx_medicines_category"),
                IndexModel([("category_slug", ASCENDING)], name="idx_medicines_category_slug"),
                IndexModel([("is_active", ASCENDING)], name="idx_medicines_active"),
                IndexModel([("in_stock", ASCENDING)], name="idx_medicines_in_stock"),
                IndexModel([("generic_name", ASCENDING)], name="idx_medicines_generic"),
                IndexModel([("brand", ASCENDING), ("strength", ASCENDING)], name="idx_medicines_brand_strength"),
            ])
        except Exception as idx_err:
            if "IndexOptionsConflict" in str(idx_err) or "IndexKeySpecsConflict" in str(idx_err) or "85" in str(idx_err):
                logger.info("Resolving conflicting text index on medicines collection...")
                try:
                    await db.medicines.drop_index("idx_medicines_text_search")
                except Exception:
                    pass
                await db.medicines.create_indexes([
                    IndexModel([("slug", ASCENDING)], unique=True, sparse=True, name="idx_medicines_slug_unique"),
                    IndexModel(
                        [("name", TEXT), ("generic_name", TEXT), ("brand", TEXT), ("manufacturer", TEXT), ("medicine_name", TEXT)],
                        name="idx_medicines_text_search"
                    ),
                    IndexModel([("category", ASCENDING)], name="idx_medicines_category"),
                    IndexModel([("category_slug", ASCENDING)], name="idx_medicines_category_slug"),
                    IndexModel([("is_active", ASCENDING)], name="idx_medicines_active"),
                    IndexModel([("in_stock", ASCENDING)], name="idx_medicines_in_stock"),
                    IndexModel([("generic_name", ASCENDING)], name="idx_medicines_generic"),
                    IndexModel([("brand", ASCENDING), ("strength", ASCENDING)], name="idx_medicines_brand_strength"),
                ])
            else:
                raise idx_err
        await db.medicine_details.create_indexes([
            IndexModel([("slug", ASCENDING)], unique=True, name="idx_medicine_details_slug_unique"),
            IndexModel([("medicine_id", ASCENDING)], name="idx_medicine_details_med_id"),
            IndexModel([("generic_name", ASCENDING)], name="idx_medicine_details_generic"),
        ])
        await db.crawler_jobs.create_indexes([
            IndexModel([("started_at", DESCENDING)], name="idx_crawler_jobs_started_at"),
            IndexModel([("status", ASCENDING)], name="idx_crawler_jobs_status"),
        ])
        await db.carts.create_indexes([
            IndexModel([("user_id", ASCENDING)], unique=True, name="idx_carts_user_id_unique"),
        ])
        await db.orders.create_indexes([
            IndexModel([("user_id", ASCENDING)], name="idx_orders_user"),
            IndexModel([("status", ASCENDING)], name="idx_orders_status"),
            IndexModel([("payment_id", ASCENDING)], name="idx_orders_payment"),
            IndexModel([("created_at", DESCENDING)], name="idx_orders_created_at"),
        ])
        await db.payments.create_indexes([
            IndexModel([("merchant_invoice_number", ASCENDING)], unique=True, name="idx_payments_invoice_unique"),
            IndexModel([("payment_id", ASCENDING)], name="idx_payments_id"),
            IndexModel([("bkash_payment_id", ASCENDING)], name="idx_payments_bkash_id"),
            IndexModel([("target_type", ASCENDING), ("target_id", ASCENDING)], name="idx_payments_target"),
            IndexModel([("status", ASCENDING)], name="idx_payments_status"),
        ])
        await db.notifications.create_indexes([
            IndexModel([("user_id", ASCENDING), ("is_read", ASCENDING)], name="idx_notifications_user_read"),
            IndexModel([("created_at", DESCENDING)], name="idx_notifications_created_at"),
        ])
        await db.audit_logs.create_indexes([
            IndexModel([("user_id", ASCENDING)], name="idx_audit_user"),
            IndexModel([("action", ASCENDING)], name="idx_audit_action"),
            IndexModel([("target_type", ASCENDING), ("target_id", ASCENDING)], name="idx_audit_target"),
            IndexModel([("created_at", DESCENDING)], name="idx_audit_created_at"),
        ])
        await db.agent_pending_actions.create_indexes([
            IndexModel([("id", ASCENDING)], unique=True, name="idx_agent_pending_id_unique"),
            IndexModel([("actor_id", ASCENDING), ("status", ASCENDING)], name="idx_agent_pending_actor_status"),
            IndexModel([("session_id", ASCENDING)], name="idx_agent_pending_session"),
            IndexModel([("expires_at", ASCENDING)], name="idx_agent_pending_expires"),
        ])
        await db.agent_audit_logs.create_indexes([
            IndexModel([("id", ASCENDING)], unique=True, name="idx_agent_audit_id_unique"),
            IndexModel([("actor_id", ASCENDING)], name="idx_agent_audit_actor"),
            IndexModel([("action", ASCENDING)], name="idx_agent_audit_action"),
            IndexModel([("timestamp", DESCENDING)], name="idx_agent_audit_timestamp"),
        ])
        await db.agent_clarifications.create_indexes([
            IndexModel([("id", ASCENDING)], unique=True, name="idx_agent_clarifications_id_unique"),
            IndexModel([("session_id", ASCENDING), ("status", ASCENDING)], name="idx_agent_clarifications_session_status"),
            IndexModel([("user_id", ASCENDING)], name="idx_agent_clarifications_user"),
            IndexModel([("expires_at", ASCENDING)], name="idx_agent_clarifications_expires"),
        ])
        await db.agent_task_context.create_indexes([
            IndexModel([("task_id", ASCENDING)], unique=True, name="idx_task_ctx_task_id_unique"),
            IndexModel([("session_id", ASCENDING), ("status", ASCENDING)], name="idx_task_ctx_session_status"),
            IndexModel([("user_id", ASCENDING), ("status", ASCENDING)], name="idx_task_ctx_user_status"),
            IndexModel([("clarification_id", ASCENDING)], name="idx_task_ctx_clarification"),
            IndexModel([("expires_at", ASCENDING)], name="idx_task_ctx_expires"),
        ])
        await db.chat_sessions.create_indexes([
            IndexModel([("id", ASCENDING)], unique=True, name="idx_chat_sessions_id_unique"),
            IndexModel([("user_id", ASCENDING), ("is_archived", ASCENDING), ("message_count", ASCENDING)], name="idx_chat_sessions_user_active_msgs"),
            IndexModel([("user_id", ASCENDING), ("is_archived", ASCENDING)], name="idx_chat_sessions_user"),
            IndexModel([("last_message_at", DESCENDING)], name="idx_chat_sessions_last_msg"),
            IndexModel([("updated_at", DESCENDING)], name="idx_chat_sessions_updated"),
        ])
        await db.chat_messages.create_indexes([
            IndexModel([("id", ASCENDING)], unique=True, name="idx_chat_messages_id_unique"),
            IndexModel([("session_id", ASCENDING), ("created_at", ASCENDING)], name="idx_chat_messages_session_time"),
        ])
        logger.info("All MongoDB indexes successfully ensured.")

        # Run safe legacy empty session cleanup on startup
        try:
            from app.modules.agent.memory.repository import AgentMemoryRepository
            repo = AgentMemoryRepository(db)
            await repo.cleanup_legacy_empty_sessions()
        except Exception as cleanup_err:
            logger.warning(f"Non-blocking startup session cleanup error: {cleanup_err}")
    except Exception as e:
        logger.error(f"Error creating MongoDB indexes: {e}")

