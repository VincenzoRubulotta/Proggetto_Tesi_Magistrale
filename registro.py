import redis
import json

class RegistroDispositivi:
    def __init__(self, host='localhost', port=6379, timeout_secondi=300):
        self.r = redis.Redis(host=host, port=port, decode_responses=True)
        
        self.timeout_secondi = timeout_secondi

    def aggiorna_dispositivo(self, payload_json):
        """Salva il dispositivo in Redis con un timer di autodistruzione (TTL)."""
        zona = payload_json.get("posizione", {}).get("nome_zona", "Zona_Sconosciuta")
        id_disp = payload_json.get("id_dispositivo")
        tipo = payload_json.get("tipo_dispositivo")
        
        if not id_disp:
            return

        chiave_redis = f"smartcity:registry:{zona}:{id_disp}"

        valore_stringa = json.dumps(payload_json)
        self.r.set(chiave_redis, valore_stringa, ex=self.timeout_secondi)

    def ottieni_dispositivi_attivi(self, zona, ts_riferimento=None):
        """Cerca in Redis i dispositivi attualmente vivi per questa zona."""
        
        pattern_ricerca = f"smartcity:registry:{zona}:*"
        chiavi_attive = self.r.keys(pattern_ricerca)
        
        dispositivi_attivi = []
        for chiave in chiavi_attive:
            dati_str = self.r.get(chiave)
            if dati_str:
                dispositivi_attivi.append(dati_str)
            
        return dispositivi_attivi
