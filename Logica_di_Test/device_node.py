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

route_env = os.getenv("PATROL_ROUTE", "")
PATROL_ROUTE = []
if route_env:
    for pt in route_env.split(";"):
        if "," in pt:
            la, lo = pt.split(",")
            PATROL_ROUTE.append((float(la.strip()), float(lo.strip())))

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
        self.route = PATROL_ROUTE
        self.route_idx = 0
        self.occupato_fino_al = 0

    def avvia_heartbeat(self, client):
        threading.Thread(target=self._loop_heartbeat, args=(client,), daemon=True).start()

        if IS_MOBILE and self.route:
            threading.Thread(target=self._loop_pattugliamento, args=(client,), daemon=True).start()

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

    def _loop_pattugliamento(self, client):
        while True:
            time.sleep(60)  
            
            if time.time() > self.occupato_fino_al and not self.in_movimento:
                self.route_idx = (self.route_idx + 1) % len(self.route)
                nuova_lat, nuova_lon = self.route[self.route_idx]
                
                self.lat = nuova_lat
                self.lon = nuova_lon
                log_to_dashboard(client, f"[{DEVICE_ID}] Pattugliamento: spostato in zona ({self.lat}, {self.lon})")

    def esegui_spostamento(self, client, target_lat, target_lon):
        self.occupato_fino_al = time.time() + 180
        log_to_dashboard(client, f"[{DEVICE_ID}] Inizio volo verso {target_lat}, {target_lon}...")
        self.in_movimento = True
        passi = 5
        for i in range(passi):
            self.lat += (target_lat - self.lat) / (passi - i)
            self.lon += (target_lon - self.lon) / (passi - i)
            time.sleep(2)
        log_to_dashboard(client, f"[{DEVICE_ID}] Arrivato a destinazione!")
        self.in_movimento = False

    def invia_simulazione(self, client, scenario="RANDOM", file_scelto= None):
        """Invia dati deterministici basati sullo scenario scelto (CRITICO o NORMALE)"""
        if TIPO in ["telecamera", "drone"]:

            if scenario == "RANDOM":
                scenario = random.choice(["CRITICO", "NORMALE"])


            cartella = os.path.join(BASE_POOL, "Telecamere", scenario)

            if not file_scelto:
                if os.path.exists(cartella) and os.listdir(cartella):
                    file_scelto = random.choice(os.listdir(cartella))
                else:
                    file_scelto = None
            
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
                        "dato_rilevato": {"allarme": "emergenza_visiva" if scenario == "CRITICO" else "nessun_allarme", "dettaglio": f"Scenario: {scenario}"},
                        "immagine_url": url_img
                    }
                    client.publish(f"smartcity/sensori/{ZONA}/{TIPO}", json.dumps(payload))
                    log_to_dashboard(client, f"[{DEVICE_ID}] Immagine ({scenario}) inviata! URL: {url_img}")
                except Exception as e:
                    log_to_dashboard(client, f"[{DEVICE_ID}] Errore invio immagine: {e}")
            else:
                log_to_dashboard(client, f"[{DEVICE_ID}] Nessuna immagine in {cartella}. Crea la cartella e aggiungile!")
        
        elif TIPO == "microfono":
            if scenario == "CRITICO":
                dati_testuali = {"allarme": "boato_rilevato", "decibel": 120, "trascrizione_audio": "Forte boato e rumori metallici."}
            else:
                dati_testuali = {"allarme": "nessuno", "decibel": 45, "trascrizione_audio": "Rumore di traffico cittadino normale."}
                
            payload = {
                "id_dispositivo": DEVICE_ID,
                "nome_dispositivo": NOME,
                "tipo_dispositivo": TIPO,
                "posizione": {"nome_zona": ZONA, "coordinate": {"latitudine": self.lat, "longitudine": self.lon}},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dato_rilevato": dati_testuali
            }
            client.publish(f"smartcity/sensori/{ZONA}/{TIPO}", json.dumps(payload))
            log_to_dashboard(client, f"[{DEVICE_ID}] Rilevamento acustico ({scenario}) inviato!")

        elif TIPO == "sensore_temperatura":
            temp = 85.5 if scenario == "CRITICO" else 22.0
            allarme = "TEMPERATURA_CRITICA" if scenario == "CRITICO" else "NESSUNO"
            payload = {
                "id_dispositivo": DEVICE_ID,
                "nome_dispositivo": NOME,
                "tipo_dispositivo": TIPO,
                "posizione": {"nome_zona": ZONA, "coordinate": {"latitudine": self.lat, "longitudine": self.lon}},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dato_rilevato": {"temperatura_rilevata": temp, "soglia_allarme": 65.0, "allarme": allarme},
                "unita_misura": "Celsius"
            }
            client.publish(f"smartcity/sensori/{ZONA}/{TIPO}", json.dumps(payload))
            log_to_dashboard(client, f"[{DEVICE_ID}] Temperatura: {temp}°C ({scenario}) inviata!")

    def elabora_comando(self, client, payload):
        comando = payload.get("comando")
        azione = payload.get("azione_tattica")
        target_gps = payload.get("target_gps")

        if azione == "SPOSTAMENTO_RICHIESTO" and IS_MOBILE and target_gps:
            self.esegui_spostamento(client, target_gps["latitudine"], target_gps["longitudine"])
            
        if comando == "RICHIEDI_DATO_EMERGENZA":
            log_to_dashboard(client, f"[{DEVICE_ID}] Orchestratore richiede verifica. Invio conferma emergenza...")
            self.invia_simulazione(client, scenario="RANDOM")

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

log_to_dashboard(client, f"[{DEVICE_ID}] ONLINE! Modalità Test controllato.")

try:
    while True:
        print(f"\n=== CONTROLLO MANUALE ({DEVICE_ID}) ===")

        if TIPO in ["telecamera", "drone"]:
            print("1 - INNESCA EMERGENZA (Scegli foto critica)")
            print("2 - CESSATO ALLARME (Scegli foto di normalità)")
            scelta = input("Seleziona lo scenario (1 o 2): ").strip()
            
            scenario_scelto = "CRITICO" if scelta == '1' else "NORMALE" if scelta == '2' else None

            if scenario_scelto:
                cartella = os.path.join(BASE_POOL, "Telecamere", scenario_scelto)
                if os.path.exists(cartella):
                    files = [f for f in os.listdir(cartella) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
                    
                    if files:
                        print(f"\n--- Immagini in {scenario_scelto} ---")
                        for i, f in enumerate(files):
                            print(f"[{i}] {f}")
                        
                        idx = input("\nDigita il numero dell'immagine da inviare: ").strip()
                        
                        if idx.isdigit() and 0 <= int(idx) < len(files):
                            foto_scelta = files[int(idx)]
                            log_to_dashboard(client, f"[{DEVICE_ID}] Invio manuale di {foto_scelta}...")
                            nodo.invia_simulazione(client, scenario=scenario_scelto, file_scelto=foto_scelta)
                        else:
                            print("Selezione non valida. Operazione annullata.")
                    else:
                        print(f"ATTENZIONE: La cartella {cartella} è vuota!")
                else:
                    print(f"Cartella {cartella} non trovata. Creala inserendo alcune immagini.")
            else:
                print("Scelta non valida. Premi 1 o 2.")

        else:
            print("Premi INVIO per inviare un'ANOMALIA.")
            print("Scrivi 'exit' per uscire.")
            scelta = input("Azione: ").strip().lower()
            
            if scelta == 'exit':
                break
            else:
                log_to_dashboard(client, f"[{DEVICE_ID}] Lancio trigger anomalia ({TIPO})...")
                nodo.invia_simulazione(client, scenario="CRITICO")
            
except KeyboardInterrupt:
    log_to_dashboard(client, f"[{DEVICE_ID}] Spegnimento...")
    client.loop_stop()
    client.disconnect()