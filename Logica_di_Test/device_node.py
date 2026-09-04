import os
import time
import json
import random
import threading
import requests
import paho.mqtt.client as mqtt

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
STORAGE_UPLOAD_URL = os.getenv("STORAGE_UPLOAD_URL", "http://storage:5000/upload")
BASE_POOL = "./Data_Pool"

DEVICE_ID = os.getenv("DEVICE_ID", "DEV_001")
NOME = os.getenv("DEVICE_NAME", "Dispositivo_Test")
TIPO = os.getenv("DEVICE_TYPE", "sensore")
IS_MOBILE = os.getenv("IS_MOBILE", "False").lower() in ("true", "1", "yes")
ZONA = os.getenv("ZONA", "Piazza_Verga")
LAT = float(os.getenv("LATITUDE", "37.5112"))
LON = float(os.getenv("LONGITUDE", "15.089"))

spec_env = os.getenv("SPECIALIZATIONS", "")
SPECIALIZZAZIONI = [s.strip() for s in spec_env.split(",") if s.strip()]

def log_to_dashboard(client, messaggio):
    print(messaggio)
    if client:
        payload = {
            "id_dispositivo": DEVICE_ID,
            "timestamp": time.strftime("%H:%M:%S"),
            "messaggio": messaggio
        }
        client.publish(f"smartcity/logs/{DEVICE_ID}", json.dumps(payload))

class DispositivoNodo:
    def __init__(self):
        self.lat = LAT
        self.lon = LON
        self.in_movimento = False

    def avvia_heartbeat(self, client):
        threading.Thread(target=self._loop_heartbeat, args=(client,), daemon=True).start()

    def _loop_heartbeat(self, client):
        topic = f"smartcity/heartbeat/{ZONA}/{TIPO}"
        while True:
            payload = {
                "id_dispositivo": DEVICE_ID,
                "nome_dispositivo": NOME,
                "tipo_dispositivo": TIPO,
                "is_mobile": IS_MOBILE,
                "specializzazioni": SPECIALIZZAZIONI,
                "posizione": {
                    "nome_zona": ZONA, 
                    "coordinate": {"latitudine": self.lat, "longitudine": self.lon}
                },
                "batteria": 85 if IS_MOBILE else 100,
                "stato": "attivo"
            }
            client.publish(topic, json.dumps(payload))
            time.sleep(3)

    def esegui_spostamento(self, client, target_lat, target_lon):
        log_to_dashboard(client, f"[{DEVICE_ID}] Inizio volo verso {target_lat}, {target_lon}...")
        self.in_movimento = True
        passi = 5
        for i in range(passi):
            self.lat += (target_lat - self.lat) / (passi - i)
            self.lon += (target_lon - self.lon) / (passi - i)
            time.sleep(2)
        log_to_dashboard(client, f"[{DEVICE_ID}] Arrivato a destinazione!")
        self.in_movimento = False

    def invia_dato_multimediale(self, client, motivo="Allarme manuale"):
        if TIPO in ["telecamera", "drone"]:
            cartella = os.path.join(BASE_POOL, "Telecamere", "Emergenze")
            file_scelto = random.choice(os.listdir(cartella)) if os.path.exists(cartella) and os.listdir(cartella) else None
            
            if file_scelto:
                try:
                    with open(os.path.join(cartella, file_scelto), 'rb') as f:
                        res = requests.post(STORAGE_UPLOAD_URL, files={'file': f})
                    url_img = res.json().get("immagine_url").replace("localhost", "storage")
                    
                    payload = {
                        "id_dispositivo": DEVICE_ID,
                        "nome_dispositivo": NOME,
                        "tipo_dispositivo": TIPO,
                        "posizione": {"nome_zona": ZONA, "coordinate": {"latitudine": self.lat, "longitudine": self.lon}},
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "dato_rilevato": {"allarme": "emergenza_visiva", "dettaglio": motivo},
                        "immagine_url": url_img
                    }
                    client.publish(f"smartcity/sensori/{ZONA}/{TIPO}", json.dumps(payload))
                    log_to_dashboard(client, f"[{DEVICE_ID}] Immagine inviata! URL: {url_img}")
                except Exception as e:
                    log_to_dashboard(client, f"[{DEVICE_ID}] Errore invio immagine: {e}")
            else:
                log_to_dashboard(client, f"[{DEVICE_ID}] Nessuna immagine trovata in {cartella}")
        
        elif TIPO == "microfono":
            cartella = os.path.join(BASE_POOL, "Microfoni", "Emergenze")
            dati_testuali = {
                "allarme": "possibile_esplosione", 
                "decibel": 120, 
                "trascrizione_audio": "Boato isolato, rumori metallici ritmici in sottofondo."
            }
            
            if os.path.exists(cartella) and os.listdir(cartella):
                file_scelto = random.choice(os.listdir(cartella))
                try:
                    with open(os.path.join(cartella, file_scelto), 'r', encoding='utf-8') as f:
                        dati_testuali = json.load(f)
                except Exception as e:
                    log_to_dashboard(client, f"[{DEVICE_ID}] Errore lettura file microfono: {e}. Uso fallback.")

            payload = {
                "id_dispositivo": DEVICE_ID,
                "nome_dispositivo": NOME,
                "tipo_dispositivo": TIPO,
                "posizione": {"nome_zona": ZONA, "coordinate": {"latitudine": self.lat, "longitudine": self.lon}},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dato_rilevato": dati_testuali
            }
            client.publish(f"smartcity/sensori/{ZONA}/{TIPO}", json.dumps(payload))
            log_to_dashboard(client, f"[{DEVICE_ID}] Inviato rilevamento acustico!")

        elif TIPO == "sensore_temperatura":
            payload = {
                "id_dispositivo": DEVICE_ID,
                "nome_dispositivo": NOME,
                "tipo_dispositivo": TIPO,
                "posizione": {"nome_zona": ZONA, "coordinate": {"latitudine": self.lat, "longitudine": self.lon}},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dato_rilevato": {"temperatura_rilevata": 78.5, "soglia_allarme": 65.0, "allarme": "TEMPERATURA_CRITICA"},
                "unita_misura": "Celsius"
            }
            client.publish(f"smartcity/sensori/{ZONA}/{TIPO}", json.dumps(payload))
            log_to_dashboard(client, f"[{DEVICE_ID}] Inviato allarme temperatura critica (78.5°C)!")

    def elabora_comando(self, client, payload):
        comando = payload.get("comando")
        azione = payload.get("azione_tattica")
        target_gps = payload.get("target_gps")

        if azione == "SPOSTAMENTO_RICHIESTO" and IS_MOBILE and target_gps:
            self.esegui_spostamento(client, target_gps["latitudine"], target_gps["longitudine"])
            
        if comando == "RICHIEDI_DATO_EMERGENZA":
            log_to_dashboard(client, f"[{DEVICE_ID}] Orchestratore richiede verifica. Invio in corso...")
            self.invia_dato_multimediale(client, motivo="Richiesta da Orchestratore")

        elif comando == "DISPIEGAMENTO_TATTICO":
            log_to_dashboard(client, f"[{DEVICE_ID}] Ordine Tattico dal Comandante: {payload.get('ordine_operativo')}")


nodo = DispositivoNodo()

def on_message(client, userdata, msg):
    try:
        topic_parts = msg.topic.split("/")
        if len(topic_parts) >= 3 and topic_parts[2] == DEVICE_ID:
            payload = json.loads(msg.payload.decode())
            nodo.elabora_comando(client, payload)
    except Exception as e:
        print(f"Errore parsing: {e}")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, 60)
client.subscribe(f"smartcity/comandi/{DEVICE_ID}")

client.loop_start()
nodo.avvia_heartbeat(client)

log_to_dashboard(client, f"[{DEVICE_ID}] ONLINE! Modalità interattiva (Premi INVIO per test).")

try:
    while True:
        input() 
        log_to_dashboard(client, f"[{DEVICE_ID}] Allarme manuale innescato!")
        nodo.invia_dato_multimediale(client, motivo="Allarme generato manualmente")
except KeyboardInterrupt:
    log_to_dashboard(client, f"[{DEVICE_ID}] Spegnimento...")
    client.loop_stop()
    client.disconnect()