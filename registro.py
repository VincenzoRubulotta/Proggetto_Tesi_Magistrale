import redis
import json

class RegistroDispositivi:
    def __init__(self, host='localhost', port=6379, timeout_secondi=300):
        self.r = redis.Redis(host=host, port=port, decode_responses=True)
        
        self.timeout_secondi = timeout_secondi

    def aggiorna_dispositivo(self, payload_json):
        """Salva il dispositivo in Redis con un timer di autodistruzione (TTL)."""
        id_disp = payload_json.get("id_dispositivo")
        if not id_disp:
            return

        coord = payload_json.get("posizione", {}).get("coordinate", {})
        lat = coord.get("latitudine")
        lon = coord.get("longitudine")

        if lat is not None and lon is not None:
            self.r.geoadd("smartcity:registry:geo", (lon, lat, id_disp))

        
        chiave_dati = f"smartcity:registry:data:{id_disp}"
        valore_stringa = json.dumps(payload_json)
        self.r.set(chiave_dati, valore_stringa, ex=self.timeout_secondi)

    def ottieni_dispositivi_attivi(self, lat, lon, raggio_km=10):
        """Estrae i dispositivi vivi nel macro-raggio (città intera) per trovare i droni."""
        try:
            ids_vicini = self.r.georadius("smartcity:registry:geo", lon, lat, raggio_km, unit='km')
        except Exception:
            ids_vicini = []
            
        dispositivi_attivi = []
        if ids_vicini:
            chiavi = [f"smartcity:registry:data:{id_d}" for id_d in ids_vicini]
            dati_raw = self.r.mget(chiavi)
            for dato in dati_raw:
                if dato:
                    dispositivi_attivi.append(dato)
                    
        return dispositivi_attivi
