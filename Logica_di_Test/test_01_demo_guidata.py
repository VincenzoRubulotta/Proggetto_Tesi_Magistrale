import os
import time
import json
import requests
from iot_core import (
    setup_mqtt, Telecamera, Microfono, Drone, 
    registro_dispositivi_locali, BASE_POOL, STORAGE_UPLOAD_URL
)

class TelecameraDemo(Telecamera):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contatore = 0

    def invia_rilevamento_esatto(self, mqtt_client, cartella_scenario, tipo_allarme="verifica_visiva_completata"):
        percorso_cartella = os.path.join(BASE_POOL, "Demo_Guidata", "Telecamere", cartella_scenario)
        try:
            file_disponibili = sorted(os.listdir(percorso_cartella))
            if not file_disponibili:
                print(f"Errore: Nessuna foto in {percorso_cartella}")
                return
                
            file_scelto = file_disponibili[self.contatore % len(file_disponibili)]
            self.contatore += 1
            
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
                print(f"[{self.id}] Inviato frame demo ({file_scelto}). URL: {url_docker}")
        except Exception as e:
            print(f"[{self.id}] Errore upload demo: {e}")

    def elabora_richiesta_agente(self, payload_ricevuto, mqtt_client):
        print(f"\n[{self.id}] 🔔 Richiesta dall'Agente ricevuta! Preparo immagine coerente...")
        cartella_scenario = self.risposta_guidata if self.risposta_guidata else "FalsoPositivo"
        time.sleep(1) 
        self.invia_rilevamento_esatto(mqtt_client, cartella_scenario)

class MicrofonoDemo(Microfono):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.contatore = 0

    def invia_rilevamento_esatto(self, mqtt_client, cartella_scenario):
        percorso_cartella = os.path.join(BASE_POOL, "Demo_Guidata", "Microfoni", cartella_scenario)
        try:
            file_disponibili = sorted(os.listdir(percorso_cartella))

            if not file_disponibili:
                print(f"Errore: Nessun file JSON/testuale in {percorso_cartella}")
                return
            
            file_scelto = file_disponibili[self.contatore % len(file_disponibili)]
            self.contatore += 1
            
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
            print(f"[{self.id}] Inviato rilevamento testuale demo: {file_scelto}")
        except Exception as e:
            print(f"[{self.id}] Errore lettura dati microfono: {e}")


def esegui_scenario_falso_positivo(mqtt_client, flotta):
    print("\n" + "="*60)
    print("SCENARIO : FALSO POSITIVO (EARLY EXIT)")
    print("="*60)

    
    for disp in flotta:
        disp.risposta_guidata = "FalsoPositivo"
        
    print("MIC_EST innesca l'architettura simulando un botto forte.")
    time.sleep(2)
    
    registro_dispositivi_locali["MIC_EST"].invia_rilevamento_esatto(mqtt_client, "FalsoPositivo")
    
    print("\n[SCENA CONSEGNATA ALL'IA]")
    print("="*60 + "\n")

def esegui_scenario_emergenza(mqtt_client, flotta):
    print("\n" + "="*60)
    print("SCENARIO : EMERGENZA REALE E DISPIEGAMENTO")
    print("="*60)
    print("Allineamento della 'verità di fondo' della zona...")
    
    for disp in flotta:
        disp.risposta_guidata = "Emergenza"
        
    print("CAM_CENTRO innesca l'evento in autonomia scattando una foto.")
    time.sleep(2)
    
    registro_dispositivi_locali["CAM_CENTRO"].invia_rilevamento_esatto(mqtt_client, "Emergenza", "possibile_incidente")
    
    print("\n[SCENA CONSEGNATA ALL'IA]")
    print("="*60 + "\n")


if __name__ == "__main__":
    print("Inizializzazione ambiente e connessione MQTT...")
    os.makedirs(os.path.join(BASE_POOL, "Demo_Guidata/Telecamere/FalsoPositivo"), exist_ok=True)
    os.makedirs(os.path.join(BASE_POOL, "Demo_Guidata/Telecamere/Emergenza"), exist_ok=True)
    os.makedirs(os.path.join(BASE_POOL, "Demo_Guidata/Microfoni/FalsoPositivo"), exist_ok=True)
    os.makedirs(os.path.join(BASE_POOL, "Demo_Guidata/Microfoni/Emergenza"), exist_ok=True)

    client = setup_mqtt()

    print("🏙️ Schieramento Flotta Demo in Piazza_Verga...")
    
    cam_nord = TelecameraDemo("CAM_NORD", "Cam_Nord", "telecamera", "Piazza_Verga", 37.5115, 15.0888)
    cam_sud = TelecameraDemo("CAM_SUD", "Cam_Sud", "telecamera", "Piazza_Verga", 37.5108, 15.0888)
    cam_centro = TelecameraDemo("CAM_CENTRO", "Cam_Centro", "telecamera", "Piazza_Verga", 37.5112, 15.0885)
    
    mic_est = MicrofonoDemo("MIC_EST", "Mic_Est", "microfono", "Piazza_Verga", 37.5112, 15.0890)
    mic_ovest = MicrofonoDemo("MIC_OVEST", "Mic_Ovest", "microfono", "Piazza_Verga", 37.5112, 15.0880)
    
    drone_1 = Drone("DRONE_01", "Falco_Tattico", "drone", "Piazza_Verga", 37.5100, 15.0800)
    
    flotta_demo = [cam_nord, cam_sud, cam_centro, mic_est, mic_ovest, drone_1]
    
    for disp in flotta_demo:
        registro_dispositivi_locali[disp.id] = disp
        disp.avvia_heartbeat(client)
        
    time.sleep(3)
    
    while True:
        print("1) Esegui Scenario A: Falso Positivo (Early Exit)")
        print("2) Esegui Scenario B: Emergenza Confermata (Dispiegamento Drone)")
        print("0) Esci")
        
        scelta = input("\nSeleziona un'opzione: ")
        
        if scelta == "1":
            esegui_scenario_falso_positivo(client, flotta_demo)
        elif scelta == "2":
            esegui_scenario_emergenza(client, flotta_demo)
        elif scelta == "0":
            print("Spegnimento simulatore in corso...")
            client.loop_stop()
            client.disconnect()
            break
        else:
            print("Scelta non valida, riprova.")