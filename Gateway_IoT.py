import os
import json
import logging
import redis
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from schema import MessaggioIoT, ValidationError,SegnaleDiVita
from memoria import MemoriaSpazioTemporale
from registro import RegistroDispositivi  

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC_ALLARMI = "smartcity/sensori/#"
MQTT_TOPIC_HEARTBEAT = "smartcity/heartbeat/#"


REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

WORKERS_COUNT = int(os.getenv("WORKERS_COUNT", 3))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, password=REDIS_PASSWORD,decode_responses=True)

gestore_memoria = MemoriaSpazioTemporale(host=REDIS_HOST, port=REDIS_PORT, finestra_secondi=120)
gestore_registro = RegistroDispositivi(host=REDIS_HOST, port=REDIS_PORT, timeout_secondi=300)

def on_message(client_instance, userdata, msg):
    topic = msg.topic
    try:
        dati_grezzi = json.loads(msg.payload.decode("utf-8"))
        
        if topic.startswith("smartcity/heartbeat/"):
            messaggio_validato = SegnaleDiVita(**dati_grezzi)
            dati_puliti = messaggio_validato.model_dump()
            gestore_registro.aggiorna_dispositivo(dati_puliti)
            print(f"[HEARTBEAT] Aggiornato sulla mappa: {messaggio_validato.id_dispositivo} ({messaggio_validato.tipo_dispositivo})")
            
        elif topic.startswith("smartcity/sensori/"):
            messaggio_validato = MessaggioIoT(**dati_grezzi)
            dati_puliti = messaggio_validato.model_dump()

            gestore_registro.aggiorna_dispositivo(dati_puliti)
            epicentro_id, lat, lon, contesto_aggiornato = gestore_memoria.aggiungi_e_pulisci(dati_puliti)
            dispositivi_attivi = gestore_registro.ottieni_dispositivi_attivi(lat, lon, raggio_km=10)

            stato_iniziale = {
                "epicentro_id": epicentro_id,
                "lat_epicentro": lat,
                "lon_epicentro": lon,
                "contesto_eventi": contesto_aggiornato,
                "dispositivi_attivi": dispositivi_attivi,
                "analisi_json": None
            }

            if r.set(f"lock_analisi:{epicentro_id}", "1", nx=True, ex=30):
                print(f"[GATEWAY] Inserisco evento all'epicentro {epicentro_id} nella coda principale.")
                r.rpush("smartcity:coda_lavori", json.dumps(stato_iniziale))
            else:
                print(f"[GATEWAY] AI occupata su {epicentro_id}. Salvo nel buffer...")
                r.rpush(f"smartcity:buffer_eventi:{epicentro_id}", json.dumps(stato_iniziale))
        
    except json.JSONDecodeError as e:
        logging.error(f"Payload malformato: {e}")
    except ValidationError as e:
        print(f"\n[SCUDO PYDANTIC] Dato bloccato! {e.errors()[0]['loc']} - {e.errors()[0]['msg']}")
    except Exception as e:
        print(f"[ERRORE GATEWAY]: {e}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_message = on_message

print("\nAvvio Gateway IoT (Ascolto MQTT -> Redis)...")
client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.subscribe([(MQTT_TOPIC_ALLARMI, 0), (MQTT_TOPIC_HEARTBEAT, 0)])
client.loop_forever()
