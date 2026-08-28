from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid
from app.common.enums import MedicineCategory
from app.core.logging import logger

SAMPLE_MEDEASY_DATASET = [
    {
        "brand": "Napa Extra",
        "generic_name": "Paracetamol + Caffeine",
        "strength": "500 mg + 65 mg",
        "dosage_form": "Tablet",
        "manufacturer": "Beximco Pharmaceuticals Ltd.",
        "unit_price": 3.00,
        "pack_size": "10 Tablets/Strip",
        "requires_prescription": False,
        "category": MedicineCategory.TABLET.value,
        "description": "Used for the relief of fever, headache, migraine, toothache, and body ache.",
        "in_stock": True,
        "stock_count": 500
    },
    {
        "brand": "Napa",
        "generic_name": "Paracetamol",
        "strength": "500 mg",
        "dosage_form": "Tablet",
        "manufacturer": "Beximco Pharmaceuticals Ltd.",
        "unit_price": 1.20,
        "pack_size": "10 Tablets/Strip",
        "requires_prescription": False,
        "category": MedicineCategory.TABLET.value,
        "description": "Effective antipyretic and analgesic for pain and fever.",
        "in_stock": True,
        "stock_count": 1000
    },
    {
        "brand": "Seclo 20",
        "generic_name": "Omeprazole",
        "strength": "20 mg",
        "dosage_form": "Capsule",
        "manufacturer": "Square Pharmaceuticals PLC",
        "unit_price": 6.00,
        "pack_size": "10 Capsules/Strip",
        "requires_prescription": False,
        "category": MedicineCategory.CAPSULE.value,
        "description": "Proton pump inhibitor used for acid reflux, GERD, and gastric ulcers.",
        "in_stock": True,
        "stock_count": 600
    },
    {
        "brand": "Monas 10",
        "generic_name": "Montelukast Sodium",
        "strength": "10 mg",
        "dosage_form": "Tablet",
        "manufacturer": "Acme Laboratories Ltd.",
        "unit_price": 17.50,
        "pack_size": "10 Tablets/Strip",
        "requires_prescription": True,
        "category": MedicineCategory.TABLET.value,
        "description": "Leukotriene receptor antagonist for prophylaxis and chronic treatment of asthma and allergic rhinitis.",
        "in_stock": True,
        "stock_count": 350
    },
    {
        "brand": "Alatrol",
        "generic_name": "Cetirizine Dihydrochloride",
        "strength": "10 mg",
        "dosage_form": "Tablet",
        "manufacturer": "Square Pharmaceuticals PLC",
        "unit_price": 4.00,
        "pack_size": "10 Tablets/Strip",
        "requires_prescription": False,
        "category": MedicineCategory.TABLET.value,
        "description": "Non-sedating antihistamine for allergic rhinitis, urticaria, and allergies.",
        "in_stock": True,
        "stock_count": 400
    },
    {
        "brand": "Fexo 120",
        "generic_name": "Fexofenadine Hydrochloride",
        "strength": "120 mg",
        "dosage_form": "Tablet",
        "manufacturer": "Square Pharmaceuticals PLC",
        "unit_price": 9.00,
        "pack_size": "10 Tablets/Strip",
        "requires_prescription": False,
        "category": MedicineCategory.TABLET.value,
        "description": "Antihistamine for seasonal allergic rhinitis and skin allergies.",
        "in_stock": True,
        "stock_count": 300
    },
    {
        "brand": "Ciprocin 500",
        "generic_name": "Ciprofloxacin",
        "strength": "500 mg",
        "dosage_form": "Tablet",
        "manufacturer": "Square Pharmaceuticals PLC",
        "unit_price": 15.00,
        "pack_size": "10 Tablets/Strip",
        "requires_prescription": True,
        "category": MedicineCategory.TABLET.value,
        "description": "Broad spectrum fluoroquinolone antibiotic for bacterial infections.",
        "in_stock": True,
        "stock_count": 250
    },
    {
        "brand": "Amodis 400",
        "generic_name": "Metronidazole",
        "strength": "400 mg",
        "dosage_form": "Tablet",
        "manufacturer": "Square Pharmaceuticals PLC",
        "unit_price": 2.50,
        "pack_size": "10 Tablets/Strip",
        "requires_prescription": True,
        "category": MedicineCategory.TABLET.value,
        "description": "Antiprotozoal and antibacterial medication for amoebiasis and giardiasis.",
        "in_stock": True,
        "stock_count": 400
    },
    {
        "brand": "Tofen Syrup",
        "generic_name": "Ketotifen Fumarate",
        "strength": "1 mg/5 ml",
        "dosage_form": "Syrup",
        "manufacturer": "Beximco Pharmaceuticals Ltd.",
        "unit_price": 75.00,
        "pack_size": "100 ml Bottle",
        "requires_prescription": False,
        "category": MedicineCategory.SYRUP.value,
        "description": "Antiallergic syrup for prophylactic management of asthma and allergic conditions.",
        "in_stock": True,
        "stock_count": 150
    },
    {
        "brand": "Neosten Cream",
        "generic_name": "Clotrimazole",
        "strength": "1%",
        "dosage_form": "Ointment",
        "manufacturer": "Beximco Pharmaceuticals Ltd.",
        "unit_price": 45.00,
        "pack_size": "10 g Tube",
        "requires_prescription": False,
        "category": MedicineCategory.OINTMENT.value,
        "description": "Broad-spectrum antifungal cream for topical fungal skin infections.",
        "in_stock": True,
        "stock_count": 120
    }
]

def map_dosage_form_to_category(dosage_form: str) -> MedicineCategory:
    df = dosage_form.strip().lower()
    if "tablet" in df:
        return MedicineCategory.TABLET
    elif "capsule" in df:
        return MedicineCategory.CAPSULE
    elif "syrup" in df or "suspension" in df or "liquid" in df:
        return MedicineCategory.SYRUP
    elif "injection" in df or "infusion" in df:
        return MedicineCategory.INJECTION
    elif "drop" in df:
        return MedicineCategory.DROPS
    elif "ointment" in df or "cream" in df or "gel" in df:
        return MedicineCategory.OINTMENT
    elif "inhaler" in df:
        return MedicineCategory.INHALER
    elif "herbal" in df:
        return MedicineCategory.HERBAL
    return MedicineCategory.OTHER

def normalize_medicine_record(raw: Dict[str, Any]) -> Dict[str, Any]:
    brand = str(raw.get("brand") or raw.get("name") or "").strip()
    generic = str(raw.get("generic_name") or raw.get("generic") or "").strip()
    strength = str(raw.get("strength") or "").strip()
    dosage_form = str(raw.get("dosage_form") or raw.get("form") or "Tablet").strip()
    manufacturer = str(raw.get("manufacturer") or raw.get("company") or "Unknown Pharma").strip()
    unit_price = float(raw.get("unit_price") or raw.get("price") or 0.0)
    pack_size = str(raw.get("pack_size") or "1 Unit").strip()
    requires_prescription = bool(raw.get("requires_prescription", False))
    description = str(raw.get("description") or "").strip()
    in_stock = bool(raw.get("in_stock", True))
    stock_count = int(raw.get("stock_count", 100))

    category = raw.get("category")
    if not category:
        category = map_dosage_form_to_category(dosage_form).value

    return {
        "id": raw.get("id") or str(uuid.uuid4()),
        "name": f"{brand} {strength}".strip() if strength not in brand else brand,
        "brand": brand,
        "generic_name": generic,
        "strength": strength,
        "dosage_form": dosage_form,
        "category": category,
        "manufacturer": manufacturer,
        "unit_price": unit_price,
        "pack_size": pack_size,
        "requires_prescription": requires_prescription,
        "description": description,
        "in_stock": in_stock,
        "stock_count": stock_count,
        "is_active": True,
        "source": "MedEasy",
        "updated_at": datetime.now(timezone.utc)
    }

async def ingest_medicine_catalog(db, items: Optional[List[Dict[str, Any]]] = None) -> int:
    dataset = items or SAMPLE_MEDEASY_DATASET
    inserted_or_updated = 0

    for item in dataset:
        doc = normalize_medicine_record(item)
        query = {
            "brand": doc["brand"],
            "strength": doc["strength"],
            "dosage_form": doc["dosage_form"]
        }
        update = {
            "$set": {
                "name": doc["name"],
                "generic_name": doc["generic_name"],
                "category": doc["category"],
                "manufacturer": doc["manufacturer"],
                "unit_price": doc["unit_price"],
                "pack_size": doc["pack_size"],
                "requires_prescription": doc["requires_prescription"],
                "description": doc["description"],
                "in_stock": doc["in_stock"],
                "stock_count": doc["stock_count"],
                "is_active": True,
                "source": "MedEasy",
                "updated_at": datetime.now(timezone.utc)
            },
            "$setOnInsert": {
                "id": doc["id"],
                "created_at": datetime.now(timezone.utc)
            }
        }
        await db.medicines.update_one(query, update, upsert=True)
        inserted_or_updated += 1

    logger.info(f"Ingested {inserted_or_updated} medicines from MedEasy source into catalog.")
    return inserted_or_updated
