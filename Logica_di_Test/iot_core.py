import os
import time
import json
import random
import threading
import requests
import paho.mqtt.client as mqtt

# --- CONFIGURAZIONI GLOBALI ---
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
STORAGE_UPLOAD_URL = "http://localhost:5000/upload"
BASE_POOL = "./Data_Pool"

registro_dispositivi_locali = {}

def setup_directory_pool():
    strutture = [
        "Telecamere/Normalita", "Telecamere/Emergenze", "Telecamere/FalsiAllarmi",
        "Microfoni/Normalita", "Microfoni/Emergenze", "Microfoni/FalsiAllarmi"
    ]
    for path in strutture:
        os.makedirs(os.path.join(BASE_POOL, path), exist_ok=True)

class DispositivoIoT:
    def __init__(self, id_disp, nome, tipo, zona, lat, lon):
        self.id = id_disp
        self.nome = nome
        self.tipo = tipo
        self.zona = zona
        self.lat = lat
        self.lon = lon
        self.attivo = True
        self.risposta_guidata = None 

    def avvia_heartbeat(self, mqtt_client):
        threading.Thread(target=self._loop_heartbeat, args=(mqtt_client,), daemon=True).start()

    def _loop_heartbeat(self, mqtt_client):
        topic = f"smartcity/heartbeat/{self.zona}/{self.tipo}"
        while self.attivo:
            payload = {
                "id_dispositivo": self.id,
                "nome_dispositivo": self.nome,
                "tipo_dispositivo": self.tipo,
                "posizione": {"nome_zona": self.zona, "coordinate": {"latitudine": self.lat, "longitudine": self.lon}},
                "batteria": 100,
                "stato": "attivo"
            }
            mqtt_client.publish(topic, json.dumps(payload))
            time.sleep(10)

    def elabora_richiesta_agente(self, payload_ricevuto, mqtt_client):
        pass

class Telecamera(DispositivoIoT):
    def invia_rilevamento(self, mqtt_client, categoria_pool, tipo_allarme):
        percorso_cartella = os.path.join(BASE_POOL, "Telecamere", categoria_pool)
        try:
            file_scelto = random.choice(os.listdir(percorso_cartella))
            percorso_completo = os.path.join(percorso_cartella, file_scelto)
            
            with open(percorso_completo, 'rb') as f:
                res = requests.post(STORAGE_UPLOAD_URL, files={'file': f})
            
            if res.status_code == 200:
                url_docker = res.json().get("immagine_url").replace("localhost", "storage")
                payload = {
                    "id_dispositivo": self.id,
                    "nome_dispositivo": self.nome,
                    "tipo_dispositivo": self.tipo,
                    "posizione": {"nome_zona": self.zona, "coordinate": {"latitudine": self.lat, "longitudine": self.lon}},
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "dato_rilevato": {"allarme": tipo_allarme},
                    "immagine_url": url_docker
                }
                mqtt_client.publish(f"smartcity/sensori/{self.zona}/{self.tipo}", json.dumps(payload))
                print(f"[{self.id}] Inviato rilevamento reale. URL: {url_docker}")
        except Exception as e:
            print(f"[{self.id}] Errore upload: {e}")

    def elabora_richiesta_agente(self, payload_ricevuto, mqtt_client):
        print(f"[{self.id}] Catturata richiesta dell'Agente. Prelevo dato e rispondo...")
        esito = self.risposta_guidata if self.risposta_guidata else random.choice(["Normalita", "Emergenze"])
        self.invia_rilevamento(mqtt_client, esito, "verifica_visiva_richiesta")

class Microfono(DispositivoIoT):
    def invia_rilevamento(self, mqtt_client, categoria_pool):
        percorso_cartella = os.path.join(BASE_POOL, "Microfoni", categoria_pool)
        try:
            file_scelto = random.choice(os.listdir(percorso_cartella))
            with open(os.path.join(percorso_cartella, file_scelto), 'r', encoding='utf-8') as f:
                dati_testuali = json.load(f)
            
            payload = {
                "id_dispositivo": self.id,
                "nome_dispositivo": self.nome,
                "tipo_dispositivo": self.tipo,
                "posizione": {"nome_zona": self.zona, "coordinate": {"latitudine": self.lat, "longitudine": self.lon}},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "dato_rilevato": dati_testuali
            }
            mqtt_client.publish(f"smartcity/sensori/{self.zona}/{self.tipo}", json.dumps(payload))
            print(f"[{self.id}] 🎙️ Inviato rilevamento testuale reale dal file '{file_scelto}'")
        except Exception as e:
            print(f"[{self.id}] Errore lettura dati microfono: {e}")

    def elabora_richiesta_agente(self, payload_ricevuto, mqtt_client):
        print(f"[{self.id}] Catturata richiesta dell'Agente. Avvio ascolto prolungato...")
        time.sleep(2) 
        esito = self.risposta_guidata if self.risposta_guidata else random.choice(["Normalita", "Emergenze"])
        self.invia_rilevamento(mqtt_client, esito)

class Drone(DispositivoIoT):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.in_movimento = False

    def elabora_richiesta_agente(self, payload_ricevuto, mqtt_client):
        if self.in_movimento:
            print(f"[{self.id}] Ordine ignorato: Unità già ingaggiata in un'altra operazione.")
            return

        target_zona = payload_ricevuto.get("zona_target", self.zona)
        ordine = payload_ricevuto.get("ordine_operativo", "Nessun ordine specifico")
        
        print(f"\n[{self.id}] ORDINE RICEVUTO!")
        print(f"[{self.id}] Messaggio Radio: '{ordine}'")
        
        self.in_movimento = True
        threading.Thread(target=self._simula_spostamento, args=(self.lat + 0.01, self.lon + 0.01), daemon=True).start()

    def _simula_spostamento(self, target_lat, target_lon):
        passi = 5
        for i in range(passi):
            self.lat += (target_lat - self.lat) / (passi - i)
            self.lon += (target_lon - self.lon) / (passi - i)
            time.sleep(3)
        print(f"[{self.id}] Arrivato a destinazione!")
        self.in_movimento = False

def on_message(client, userdata, msg):
    try:
        topic_parts = msg.topic.split("/")
        if len(topic_parts) >= 3:
            disp_target = topic_parts[2]
            if disp_target in registro_dispositivi_locali:
                payload = json.loads(msg.payload.decode())
                registro_dispositivi_locali[disp_target].elabora_richiesta_agente(payload, client)
    except Exception as e:
        print(f"Errore parsing messaggio: {e}")

def setup_mqtt():
    setup_directory_pool()
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    client.subscribe("smartcity/comandi/#")
    client.loop_start()
    return client