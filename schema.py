from pydantic import BaseModel, Field, ValidationError
from typing import Any, Optional, Dict

class PosizioneDispositivo(BaseModel):
    nome_zona: str = Field(..., description="Il nome dell'area o del quartiere (es. Piazza_Verga)")
    coordinate: Optional[Dict[str, float]] = Field(None, description="Coordinate GPS o locali")

class MessaggioIoT(BaseModel):
    id_dispositivo: str = Field(..., description="L'identificativo univoco del sensore (es. CAM_001)")
    nome_dispositivo: str
    tipo_dispositivo: str
    posizione: PosizioneDispositivo
    timestamp: str
    dato_rilevato: Any 
    unita_misura: Optional[str] = None
