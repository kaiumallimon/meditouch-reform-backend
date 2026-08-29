import asyncio
import json
import uuid
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Set, AsyncGenerator
from motor.motor_asyncio import AsyncIOMotorDatabase
from app.modules.pharmacy.schemas import CrawlerSettingsModel, CrawlerJobStatusResponse
from app.core.logging import logger

def resolve_full_image_url(base_url: str, img_path: Optional[str]) -> Optional[str]:
    """Ensure product image url is stored with full absolute url."""
    if not img_path:
        return None
    img_str = str(img_path).strip()
    if img_str.startswith("http://") or img_str.startswith("https://"):
        return img_str
    clean_base = base_url.rstrip("/")
    clean_path = img_str if img_str.startswith("/") else f"/{img_str}"
    return f"{clean_base}{clean_path}"

class MedEasyCrawlerManager:
    _instance: Optional["MedEasyCrawlerManager"] = None

    def __init__(self):
        self.current_job: CrawlerJobStatusResponse = CrawlerJobStatusResponse()
        self._cancel_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._subscribers: Set[asyncio.Queue] = set()

    @classmethod
    def get_instance(cls) -> "MedEasyCrawlerManager":
        if cls._instance is None:
            cls._instance = MedEasyCrawlerManager()
        return cls._instance

    def broadcast_event(self, event_type: str, data: Dict[str, Any]):
        """Broadcast a real-time event to all connected SSE clients."""
        payload = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except (asyncio.QueueFull, Exception):
                pass

    def _append_log(self, msg: str):
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {msg}"
        self.current_job.logs.append(log_entry)
        if len(self.current_job.logs) > 100:
            self.current_job.logs = self.current_job.logs[-100:]
        logger.info(f"[Crawler] {msg}")

        # Broadcast real-time log event to SSE subscribers
        self.broadcast_event("LOG", {
            "log": log_entry,
            "job_id": self.current_job.job_id,
            "status": self.current_job.status
        })

    async def subscribe_stream(self) -> AsyncGenerator[str, None]:
        """Async generator yielding SSE formatted events for connected clients."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)

        # 1. Send initial state snapshot immediately
        init_payload = {
            "type": "INIT",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "job": self.current_job.model_dump(mode="json"),
                "is_running": self.current_job.is_running,
                "status": self.current_job.status,
            }
        }
        yield f"data: {json.dumps(init_payload)}\n\n"

        try:
            while True:
                try:
                    # Wait for next event or send keepalive ping after 12s
                    event = await asyncio.wait_for(queue.get(), timeout=12.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # SSE Keep-Alive comment to maintain active HTTP stream
                    yield ": keep-alive\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        finally:
            self._subscribers.discard(queue)

    async def get_status(self, db: AsyncIOMotorDatabase) -> CrawlerJobStatusResponse:
        return self.current_job

    async def stop_crawler(self) -> CrawlerJobStatusResponse:
        async with self._lock:
            if self.current_job.is_running:
                self._cancel_event.set()
                self._append_log("Crawler stop request initiated by admin.")
                self.current_job.status = "STOPPING"
                self.broadcast_event("STOPPING", {
                    "job_id": self.current_job.job_id,
                    "status": "STOPPING"
                })
            return self.current_job

    async def start_crawler(
        self,
        db: AsyncIOMotorDatabase,
        settings: CrawlerSettingsModel,
        category_slug: str = "otc-medicine",
        start_page: int = 1,
        max_pages: Optional[int] = None,
        admin_id: Optional[str] = None
    ) -> CrawlerJobStatusResponse:
        async with self._lock:
            if self.current_job.is_running:
                return self.current_job

            self._cancel_event.clear()
            job_id = str(uuid.uuid4())
            self.current_job = CrawlerJobStatusResponse(
                job_id=job_id,
                is_running=True,
                status="RUNNING",
                category_slug=category_slug,
                current_page=start_page,
                total_pages=0,
                total_products_found=0,
                inserted_count=0,
                skipped_count=0,
                failed_count=0,
                started_at=datetime.now(timezone.utc),
                logs=[]
            )
            self._append_log(f"Crawler started for category: {category_slug} (Page {start_page})")

            self.broadcast_event("CRAWL_STARTED", {
                "job_id": job_id,
                "category_slug": category_slug,
                "start_page": start_page,
                "max_pages": max_pages,
                "status": "RUNNING"
            })

            # Spawn decoupled background async task on server loop
            self._task = asyncio.create_task(
                self._run_crawler_task(
                    db=db,
                    settings=settings,
                    category_slug=category_slug,
                    start_page=start_page,
                    max_pages=max_pages,
                    job_id=job_id,
                    admin_id=admin_id
                )
            )

            return self.current_job

    async def _run_crawler_task(
        self,
        db: AsyncIOMotorDatabase,
        settings: CrawlerSettingsModel,
        category_slug: str,
        start_page: int,
        max_pages: Optional[int],
        job_id: str,
        admin_id: Optional[str]
    ):
        page = start_page
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
        }

        # Record crawler job in DB
        await db.crawler_jobs.insert_one({
            "id": job_id,
            "category_slug": category_slug,
            "status": "RUNNING",
            "start_page": start_page,
            "max_pages": max_pages,
            "inserted_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "started_at": datetime.now(timezone.utc),
            "triggered_by": admin_id,
        })

        try:
            async with httpx.AsyncClient(timeout=25.0, follow_redirects=True, headers=headers) as client:
                while True:
                    if self._cancel_event.is_set():
                        self.current_job.status = "STOPPED"
                        self.current_job.is_running = False
                        self._append_log("Crawler execution stopped as requested.")
                        self.broadcast_event("STOPPED", {
                            "job_id": job_id,
                            "inserted_count": self.current_job.inserted_count,
                            "skipped_count": self.current_job.skipped_count,
                        })
                        break

                    self.current_job.current_page = page
                    category_url = f"{settings.api_base_url.rstrip('/')}/api/patient/category-products/?category_slug={category_slug}&page={page}"
                    self._append_log(f"Fetching category page {page} from {category_url}")

                    try:
                        res = await client.get(category_url)
                        if res.status_code != 200:
                            self._append_log(f"Failed to fetch page {page}: HTTP {res.status_code}")
                            self.current_job.failed_count += 1
                            break
                        data = res.json()
                    except Exception as e:
                        self._append_log(f"Error fetching page {page}: {str(e)}")
                        self.current_job.failed_count += 1
                        break

                    products = data.get("category_products", [])
                    pagination_info = data.get("pagination_info", {})
                    total_pages = pagination_info.get("total_pages", page)
                    product_count = pagination_info.get("product_count", len(products))
                    has_next = pagination_info.get("has_next", False)

                    self.current_job.total_pages = total_pages
                    self.current_job.total_products_found = product_count

                    self.broadcast_event("PAGE_STARTED", {
                        "current_page": page,
                        "total_pages": total_pages,
                        "total_products_found": product_count,
                        "page_items_count": len(products),
                        "inserted_count": self.current_job.inserted_count,
                        "skipped_count": self.current_job.skipped_count,
                    })

                    self._append_log(f"Page {page}/{total_pages}: Processing {len(products)} products...")

                    for prod in products:
                        if self._cancel_event.is_set():
                            break

                        slug = prod.get("slug")
                        if not slug:
                            continue

                        med_name = prod.get("medicine_name") or prod.get("slug") or "Unknown"

                        # Duplicate checking - idempotency
                        existing = await db.medicines.find_one({"slug": slug})
                        if existing:
                            self.current_job.skipped_count += 1
                            self._append_log(f"Skipped existing: {med_name} ({slug})")
                            self.broadcast_event("MEDICINE_SKIPPED", {
                                "slug": slug,
                                "medicine_name": med_name,
                                "skipped_count": self.current_job.skipped_count,
                                "inserted_count": self.current_job.inserted_count,
                            })
                            continue

                        # Resolve full image URL
                        raw_img = prod.get("medicine_image")
                        full_img = resolve_full_image_url(settings.api_base_url, raw_img)

                        # Resolve unit prices
                        raw_unit_prices = prod.get("unit_prices", [])
                        unit_prices = []
                        for up in raw_unit_prices:
                            try:
                                unit_prices.append({
                                    "id": up.get("id"),
                                    "unit": str(up.get("unit", "1 Unit")),
                                    "unit_size": int(up.get("unit_size", 1)),
                                    "price": float(up.get("price", 0.0)),
                                })
                            except Exception:
                                continue

                        default_price = unit_prices[0]["price"] if unit_prices else float(prod.get("price", 0.0) or 0.0)
                        default_pack = unit_prices[0]["unit"] if unit_prices else "1 Unit"

                        # Fetch detail page data from Next.js endpoint
                        detail_url = f"{settings.next_data_base_url.rstrip('/')}/_next/data/{settings.session_id}/en/medicines/{slug}.json?medicines=medicines&slug={slug}"
                        p_info: Dict[str, Any] = {}
                        med_details: Dict[str, Any] = {}
                        related_meds: List[Dict[str, Any]] = []

                        try:
                            detail_res = await client.get(detail_url)
                            if detail_res.status_code == 200:
                                detail_data = detail_res.json()
                                page_props = detail_data.get("pageProps", {})
                                p_info = page_props.get("productInfo", {})
                                p_details = page_props.get("productDetails", {})
                                med_details = p_details.get("medicine_details", {})
                                related_meds = p_details.get("related_medicines", [])

                                # Ensure image in productInfo has full url
                                if p_info.get("medicine_image"):
                                    p_info["medicine_image"] = resolve_full_image_url(
                                        settings.api_base_url, p_info["medicine_image"]
                                    )
                                for rm in related_meds:
                                    if rm.get("medicine_image"):
                                        rm["medicine_image"] = resolve_full_image_url(
                                            settings.api_base_url, rm["medicine_image"]
                                        )
                            else:
                                self._append_log(f"Detail fetch ({slug}): HTTP {detail_res.status_code}, using catalog fallback")
                        except Exception as e:
                            self._append_log(f"Detail fetch error for {slug}: {str(e)}")

                        # Insert into db.medicines
                        medicine_id = str(uuid.uuid4())
                        med_doc = {
                            "id": medicine_id,
                            "medeasy_id": prod.get("id"),
                            "medicine_name": med_name,
                            "name": f"{med_name} {prod.get('strength', '')}".strip(),
                            "brand": med_name,
                            "generic_name": prod.get("generic_name", ""),
                            "strength": prod.get("strength", ""),
                            "dosage_form": prod.get("category_name", "Tablet"),
                            "category": (prod.get("category_name") or "TABLET").upper(),
                            "category_name": prod.get("category_name", "Tablet"),
                            "category_slug": category_slug,
                            "slug": slug,
                            "manufacturer": prod.get("manufacturer_name", "Unknown Pharma"),
                            "manufacturer_name": prod.get("manufacturer_name", "Unknown Pharma"),
                            "manufacturer_slug": prod.get("manufacturer_slug"),
                            "unit_price": default_price,
                            "pack_size": default_pack,
                            "unit_prices": unit_prices,
                            "discount_type": prod.get("discount_type", "Percentage"),
                            "discount_value": float(prod.get("discount_value", 0.0) or 0.0),
                            "is_discountable": bool(prod.get("is_discountable", False)),
                            "is_available": bool(prod.get("is_available", True)),
                            "rx_required": bool(prod.get("rx_required", False)),
                            "requires_prescription": bool(prod.get("rx_required", False)),
                            "medicine_image": full_img,
                            "description": f"{med_name} ({prod.get('generic_name', '')}) by {prod.get('manufacturer_name', '')}",
                            "in_stock": bool(prod.get("is_available", True)),
                            "stock_count": 100,
                            "is_active": True,
                            "source": "MedEasy",
                            "created_at": datetime.now(timezone.utc),
                            "updated_at": datetime.now(timezone.utc)
                        }

                        await db.medicines.insert_one(med_doc)

                        # Insert into db.medicine_details
                        detail_doc = {
                            "id": str(uuid.uuid4()),
                            "medicine_id": medicine_id,
                            "slug": slug,
                            "medicine_name": med_name,
                            "generic_name": prod.get("generic_name", ""),
                            "category_name": prod.get("category_name", "Tablet"),
                            "category_slug": category_slug,
                            "manufacturer_name": prod.get("manufacturer_name", "Unknown Pharma"),
                            "meta_title": med_details.get("Meta Title") or f"{med_name} - Uses, Dosage, Side Effects",
                            "meta_description": med_details.get("Meta Description") or f"Learn about {med_name} ({prod.get('generic_name', '')})",
                            "product_info": p_info if p_info else prod,
                            "medicine_details": med_details,
                            "related_medicines": related_meds,
                            "created_at": datetime.now(timezone.utc),
                            "updated_at": datetime.now(timezone.utc)
                        }

                        await db.medicine_details.update_one(
                            {"slug": slug},
                            {"$set": detail_doc},
                            upsert=True
                        )

                        self.current_job.inserted_count += 1
                        self._append_log(f"Inserted: {med_name} ({slug}) with full details")

                        # Broadcast real-time SSE MEDICINE_INSERTED event
                        self.broadcast_event("MEDICINE_INSERTED", {
                            "medicine": {
                                "id": medicine_id,
                                "medicine_name": med_name,
                                "brand": med_name,
                                "generic_name": prod.get("generic_name", ""),
                                "strength": prod.get("strength", ""),
                                "dosage_form": prod.get("category_name", "Tablet"),
                                "category_name": prod.get("category_name", "Tablet"),
                                "category_slug": category_slug,
                                "slug": slug,
                                "manufacturer_name": prod.get("manufacturer_name", "Unknown Pharma"),
                                "unit_price": default_price,
                                "pack_size": default_pack,
                                "unit_prices": unit_prices,
                                "rx_required": bool(prod.get("rx_required", False)),
                                "medicine_image": full_img,
                                "in_stock": True,
                                "stock_count": 100,
                            },
                            "inserted_count": self.current_job.inserted_count,
                            "skipped_count": self.current_job.skipped_count,
                            "current_page": page,
                            "total_pages": total_pages,
                        })

                        # Rate limiting delay between medicine detail requests
                        if settings.rate_limit_delay_seconds > 0:
                            await asyncio.sleep(settings.rate_limit_delay_seconds)

                    # Check next page condition
                    if max_pages and page >= max_pages:
                        self._append_log(f"Reached max pages limit: {max_pages}")
                        break

                    if not has_next or page >= total_pages:
                        self._append_log(f"Reached end of category catalog (Page {page}/{total_pages})")
                        break

                    page += 1
                    await asyncio.sleep(0.4)

            if not self._cancel_event.is_set():
                self.current_job.status = "COMPLETED"
                self.current_job.is_running = False
                self._append_log(
                    f"Crawl completed! Inserted: {self.current_job.inserted_count}, "
                    f"Skipped: {self.current_job.skipped_count}, Failed: {self.current_job.failed_count}"
                )
                self.broadcast_event("COMPLETED", {
                    "job_id": job_id,
                    "inserted_count": self.current_job.inserted_count,
                    "skipped_count": self.current_job.skipped_count,
                    "failed_count": self.current_job.failed_count,
                    "total_pages": self.current_job.total_pages,
                })

        except Exception as e:
            self.current_job.status = "FAILED"
            self.current_job.is_running = False
            self.current_job.failed_count += 1
            self._append_log(f"Crawler failed with unhandled error: {str(e)}")
            logger.error(f"Crawler failed: {e}", exc_info=True)
            self.broadcast_event("FAILED", {
                "job_id": job_id,
                "error": str(e),
            })

        finally:
            self.current_job.finished_at = datetime.now(timezone.utc)
            self.current_job.is_running = False

            # Update job record in database
            await db.crawler_jobs.update_one(
                {"id": job_id},
                {
                    "$set": {
                        "status": self.current_job.status,
                        "current_page": self.current_job.current_page,
                        "total_pages": self.current_job.total_pages,
                        "total_products_found": self.current_job.total_products_found,
                        "inserted_count": self.current_job.inserted_count,
                        "skipped_count": self.current_job.skipped_count,
                        "failed_count": self.current_job.failed_count,
                        "finished_at": self.current_job.finished_at,
                        "logs": self.current_job.logs[-50:]
                    }
                }
            )
