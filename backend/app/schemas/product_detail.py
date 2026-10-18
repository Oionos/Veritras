from pydantic import BaseModel
from app.schemas.product import ProductResponse
from app.schemas.shipment import CheckpointResponse, CustodyTransferResponse


class ProductDetailResponse(BaseModel):
    product: ProductResponse
    history: list[CheckpointResponse]
    transfers: list[CustodyTransferResponse]
