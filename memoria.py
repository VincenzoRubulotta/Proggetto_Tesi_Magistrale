import redis
import json
from datetime import datetime
import time

class MemoriaSpazioTemporale:
    def __init__(self, host='localhost', port=6379, finestra_secondi=120):
        self.finestra_secondi = finestra_secondi
        self.r = redis.Redis(host=host, port=port, decode_responses=True)

    def _estrai_timestamp_evento(self, ts_str):
        try:
            ts_str = ts_str.replace('Z', '+00:00')
            return datetime.fromisoformat(ts_str).timestamp()
        except Exception:
            return time.time()

    def aggiungi_e_pulisci(self, payload_json):
        coord = payload_json.get("posizione", {}).get("coordinate", {})
        lat = coord.get("latitudine", 0.0)
        lon = coord.get("longitudine", 0.0)
        id_disp = payload_json.get("id_dispositivo", "UNK")
        ts_evento = self._estrai_timestamp_evento(payload_json.get("timestamp", ""))
        
        epicentri_mappati = self.r.zrange("smartcity:epicentri:geo", 0, -1)
        for epi in epicentri_mappati:
            if not self.r.exists(f"smartcity:memory:{epi}"):
                self.r.zrem("smartcity:epicentri:geo", epi)
                
        try:
            epicentri_vicini = self.r.georadius("smartcity:epicentri:geo", lon, lat, 100, unit='m')
        except Exception:
            epicentri_vicini = []
            
        if epicentri_vicini:
            epicentro_id = epicentri_vicini[0]
        else:
            epicentro_id = f"epi_{int(ts_evento)}_{id_disp}"
            try:
                self.r.geoadd("smartcity:epicentri:geo", mapping={epicentro_id: (lon, lat)})
            except TypeError:
                self.r.geoadd("smartcity:epicentri:geo", lon, lat, epicentro_id)

        chiave_redis = f"smartcity:memory:{epicentro_id}"
        valore_stringa = json.dumps(payload_json)
        
        self.r.zadd(chiave_redis, {valore_stringa: ts_evento})
        soglia_vecchiaia = ts_evento - self.finestra_secondi
        self.r.zremrangebyscore(chiave_redis, '-inf', soglia_vecchiaia)
        
        self.r.expire(chiave_redis, 60 + self.finestra_secondi)
        
        eventi_salvati_stringa = self.r.zrange(chiave_redis, 0, -1)
        storico_recente = [json.loads(evento) for evento in eventi_salvati_stringa]
        
        return epicentro_id, lat, lon, storico_recente