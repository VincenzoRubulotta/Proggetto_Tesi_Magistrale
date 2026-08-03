import os
import json
import logging
import redis
import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from schema import MessaggioIoT, ValidationError
from memoria import MemoriaSpazioTemporale
from registro import RegistroDispositivi  

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC_IN = os.getenv("MQTT_TOPIC_IN", "smartcity/sensori/#")

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

gestore_memoria = MemoriaSpazioTemporale(finestra_secondi=10)
gestore_registro = RegistroDispositivi(timeout_secondi=300)

def on_message(client_instance, userdata, msg):
    try:
        dati_grezzi = json.loads(msg.payload.decode("utf-8"))
        messaggio_validato = MessaggioIoT(**dati_grezzi)
        dati_puliti = messaggio_validato.model_dump()

        gestore_registro.aggiorna_dispositivo(dati_puliti)
        zona, contesto_aggiornato = gestore_memoria.aggiungi_e_pulisci(dati_puliti)
        dispositivi_attivi = gestore_registro.ottieni_dispositivi_attivi(zona)

        stato_iniziale = {
            "zona": zona,
            "contesto_eventi": contesto_aggiornato,
            "dispositivi_attivi": dispositivi_attivi,
            "analisi_json": None
        }

        if r.set(f"lock_analisi:{zona}", "1", nx=True, ex=15):
            r.rpush("smartcity:coda_lavori", json.dumps(stato_iniziale))
            
            r.ltrim("smartcity:coda_lavori", -10, -1)
            
            print(f"[GATEWAY] Messaggio salvato. Lock attivato per {zona}!")
        else:
            print(f"[GATEWAY] Ignoro evento per {zona}: indagine AI già in corso.")
        
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
client.subscribe(MQTT_TOPIC_IN)
client.loop_forever()
