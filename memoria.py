import redis
import json
from datetime import datetime
import time

class MemoriaSpazioTemporale:
    def __init__(self, host='localhost', port=6379, finestra_secondi=10):
        self.finestra_secondi = finestra_secondi
        self.r = redis.Redis(host=host, port=port, decode_responses=True, protocol=2)

    def _estrai_timestamp_evento(self, ts_str):
        try:
            ts_str = ts_str.replace('Z', '+00:00')
            return datetime.fromisoformat(ts_str).timestamp()
        except Exception:
            return time.time()

    def aggiungi_e_pulisci(self, payload_json):
        zona = payload_json.get("posizione", {}).get("nome_zona", "Zona_Sconosciuta")
        ts_evento = self._estrai_timestamp_evento(payload_json.get("timestamp", ""))
        
        chiave_redis = f"smartcity:memory:{zona}"
        
        valore_stringa = json.dumps(payload_json)

        self.r.zadd(chiave_redis, {valore_stringa: ts_evento})
        soglia_vecchiaia = ts_evento - self.finestra_secondi
        
        self.r.zremrangebyscore(chiave_redis, '-inf', soglia_vecchiaia)

        self.r.expire(chiave_redis, 60)

        eventi_salvati_stringa = self.r.zrange(chiave_redis, 0, -1)
        
        storico_recente = [json.loads(evento) for evento in eventi_salvati_stringa]
        
        return zona, storico_recente
