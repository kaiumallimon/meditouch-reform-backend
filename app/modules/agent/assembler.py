from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from app.core.logging import logger


class StructuredComponent(BaseModel):
    """Generic representation of a validated, server-side UI component."""
    type: str  # e.g., "medicine_card", "doctor_card", "appointment_card"
    data: Dict[str, Any]


class MedicineCardItem(BaseModel):
    """Authoritative medicine card item constructed strictly from catalog data."""
    id: str
    slug: Optional[str] = None
    brand: str
    generic_name: Optional[str] = None
    strength: Optional[str] = None
    dosage_form: Optional[str] = "Tablet"
    unit_price: Optional[float] = None
    pack_size: Optional[str] = None
    in_stock: bool = True
    stock_count: Optional[int] = None
    requires_prescription: bool = False
    image: Optional[str] = None
    manufacturer: Optional[str] = None


class ResponseAssembler:
    """
    Centralized Response Assembly Stage.

    Architectural Invariant:
    - Tool execution does NOT directly emit UI components to the client.
    - Tools produce raw domain data; ResponseAssembler collects and sanitizes it during the run.
    - When the LLM finishes text streaming, ResponseAssembler constructs the authoritative
      structured UI components (e.g. medicine cards) and attaches them to the final response.
    - If the turn terminates early (error or clarification), buffered components are discarded.
    """

    def __init__(self, response_id: str):
        self.response_id = response_id
        self._raw_tool_results: List[Dict[str, Any]] = []
        self._medicine_cards: List[Dict[str, Any]] = []
        self._components: List[Dict[str, Any]] = []

    def record_tool_result(self, tool_name: str, arguments: Dict[str, Any], result: Any) -> None:
        """Buffers raw tool execution results internally without pushing to frontend."""
        self._raw_tool_results.append({
            "tool_name": tool_name,
            "arguments": arguments,
            "result": result,
        })

        # Process catalog search results for eventual final response assembly
        if tool_name == "search_medicines" and isinstance(result, dict):
            meds = result.get("medicines") or []
            for item in meds:
                if isinstance(item, dict) and item.get("id"):
                    # Deduplicate by medicine ID
                    if not any(m.get("id") == item.get("id") for m in self._medicine_cards):
                        self._medicine_cards.append(item)

        elif tool_name == "get_medicine_details" and isinstance(result, dict):
            med_id = result.get("id")
            if med_id and not any(m.get("id") == med_id for m in self._medicine_cards):
                card = {
                    "id": str(med_id),
                    "slug": result.get("slug"),
                    "brand": result.get("brand") or result.get("name") or result.get("medicine_name", ""),
                    "generic_name": result.get("generic_name"),
                    "strength": result.get("strength"),
                    "dosage_form": result.get("dosage_form", "Tablet"),
                    "unit_price": result.get("unit_price"),
                    "pack_size": result.get("pack_size"),
                    "in_stock": result.get("in_stock", True),
                    "stock_count": result.get("stock_count"),
                    "requires_prescription": bool(result.get("requires_prescription") or result.get("rx_required")),
                    "image": result.get("medicine_image") or result.get("image"),
                    "manufacturer": result.get("manufacturer") or result.get("manufacturer_name"),
                }
                self._medicine_cards.append(card)

    def get_medicine_cards(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Returns buffered, deduplicated medicine cards."""
        return self._medicine_cards[:limit]

    def assemble_final_components(self) -> List[Dict[str, Any]]:
        """
        Assembles all structured UI components to be delivered with the final response.
        """
        components: List[Dict[str, Any]] = []
        if self._medicine_cards:
            components.append({
                "type": "medicine_cards",
                "medicines": self._medicine_cards[:5],
            })
        return components

    def clear(self) -> None:
        """Discards all buffered components (used on clarification or error abort)."""
        self._raw_tool_results.clear()
        self._medicine_cards.clear()
        self._components.clear()
