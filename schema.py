from pydantic import BaseModel, Field, ValidationError
from typing import Any, Optional, Dict,List

class PosizioneDispositivo(BaseModel):
    nome_zona: str = Field(..., description="Il nome dell'area o del quartiere (es. Piazza_Verga)")
    coordinate: Optional[Dict[str, float]] = Field(None, description="Coordinate GPS o locali")

class MessaggioIoT(BaseModel):
    id_dispositivo: str = Field(..., description="L'identificativo univoco del sensore (es. CAM_001)")
    nome_dispositivo: str
    tipo_dispositivo: str
    is_mobile: bool = Field(False, description="Indica se il dispositivo può muoversi fisicamente")
    specializzazioni: Optional[List[str]] = Field(default_factory=list, description="Cosa sa riconoscere il sensore (es. ['incendi', 'incidenti', 'armi'])")
    posizione: PosizioneDispositivo
    timestamp: str
    dato_rilevato: Any 
    unita_misura: Optional[str] = None
    immagine_url: Optional[str] = None

class SegnaleDiVita(BaseModel):
    id_dispositivo: str = Field(..., description="L'identificativo univoco (es. DRONE_001)")
    nome_dispositivo: str
    tipo_dispositivo: str
    is_mobile: bool = Field(False, description="Indica se il dispositivo può muoversi fisicamente")
    specializzazioni: Optional[List[str]] = Field(default_factory=list, description="Cosa sa riconoscere il sensore")
    posizione: PosizioneDispositivo
    batteria: Optional[int] = Field(None, description="Percentuale batteria")
    stato: Optional[str] = Field("attivo", description="Stato operativo del dispositivo")
