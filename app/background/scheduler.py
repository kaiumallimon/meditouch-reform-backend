import asyncio
from datetime import datetime, timezone, timedelta
from app.db.mongodb import db_manager
from app.common.enums import AppointmentStatus, TimeslotStatus, NotificationType
from app.core.logging import logger
import uuid

async def run_appointment_30min_reminders():
    try:
        db = db_manager.db
        if db is None:
            return

        now = datetime.now(timezone.utc)
        window_from = now + timedelta(minutes=25)
        window_to = now + timedelta(minutes=35)

        cursor = db.appointments.find({
            "status": AppointmentStatus.CONFIRMED.value,
            "start_time": {"$gte": window_from, "$lte": window_to},
            "reminder_30min_sent": {"$ne": True}
        })

        appointments = await cursor.to_list(length=100)
        for apt in appointments:
            apt_id = apt["id"]
            patient_id = apt.get("patient_id")
            doctor_doc = await db.doctors.find_one({"id": apt.get("doctor_id")})
            doctor_user_id = doctor_doc.get("user_id") if doctor_doc else None

            if patient_id:
                await db.notifications.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": patient_id,
                    "type": NotificationType.APPOINTMENT_REMINDER_30MIN.value,
                    "title": "Upcoming Consultation in 30 Minutes",
                    "message": f"Your consultation with Dr. {apt.get('doctor_name')} starts in 30 minutes. Please ensure a stable internet connection.",
                    "payload": {"appointment_id": apt_id},
                    "is_read": False,
                    "created_at": datetime.now(timezone.utc)
                })

            if doctor_user_id:
                await db.notifications.insert_one({
                    "id": str(uuid.uuid4()),
                    "user_id": doctor_user_id,
                    "type": NotificationType.APPOINTMENT_REMINDER_30MIN.value,
                    "title": "Upcoming Consultation in 30 Minutes",
                    "message": f"Consultation with {apt.get('patient_name')} starts in 30 minutes.",
                    "payload": {"appointment_id": apt_id},
                    "is_read": False,
                    "created_at": datetime.now(timezone.utc)
                })

            await db.appointments.update_one(
                {"id": apt_id},
                {"$set": {"reminder_30min_sent": True, "updated_at": datetime.now(timezone.utc)}}
            )
            logger.info(f"30-min reminder sent for appointment {apt_id}")

    except Exception as e:
        logger.error(f"Error running 30-min reminders background job: {e}")

async def run_expired_reservations_cleanup():
    try:
        db = db_manager.db
        if db is None:
            return

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        cursor = db.appointments.find({
            "status": AppointmentStatus.PENDING_PAYMENT.value,
            "created_at": {"$lt": cutoff}
        })

        expired = await cursor.to_list(length=100)
        for apt in expired:
            timeslot_id = apt.get("timeslot_id")
            if timeslot_id:
                await db.timeslots.update_one(
                    {"id": timeslot_id, "status": TimeslotStatus.RESERVED.value},
                    {"$set": {"status": TimeslotStatus.AVAILABLE.value, "updated_at": datetime.now(timezone.utc)}}
                )

            await db.appointments.update_one(
                {"id": apt["id"]},
                {"$set": {"status": AppointmentStatus.EXPIRED.value, "updated_at": datetime.now(timezone.utc)}}
            )
            logger.info(f"Expired unpaid appointment {apt['id']} and released timeslot {timeslot_id}")

    except Exception as e:
        logger.error(f"Error running expired reservations cleanup job: {e}")

async def background_scheduler_loop(interval_seconds: int = 60):
    logger.info("Starting background scheduler loop...")
    while True:
        try:
            await run_appointment_30min_reminders()
            await run_expired_reservations_cleanup()
        except asyncio.CancelledError:
            logger.info("Background scheduler loop cancelled.")
            break
        except Exception as e:
            logger.error(f"Scheduler loop error: {e}")
        await asyncio.sleep(interval_seconds)
