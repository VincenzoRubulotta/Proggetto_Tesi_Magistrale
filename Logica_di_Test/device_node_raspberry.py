import os
import json
import time
import requests
import threading
import cv2
import paho.mqtt.client as mqtt

# ==========================================
# CONFIGURAZIONE RETE E DISPOSITIVO
# ==========================================

IP_INFRASTRUTTURA = ""  

MQTT_BROKER = IP_INFRASTRUTTURA
MQTT_PORT = 1883
STORAGE_UPLOAD_URL = f"http://{IP_INFRASTRUTTURA}:5000/upload"

DEVICE_ID = "CAM_RASPBERRY"
NOME = "Telecamera_Fisica_Lab"
TIPO = "telecamera"
ZONA = "Piazza_Verga"

def scatta_foto():
    """Usa OpenCV per catturare un frame dalla fotocamera della Raspberry"""
    percorso_temp = "/tmp/foto_live.jpg"
    print("\nAzionamento fotocamera in corso...")
    
    cap = cv2.VideoCapture(0)
    
    if not cap.isOpened():
        print("[ERRORE] Impossibile accedere alla fotocamera tramite OpenCV.")
        return None

    time.sleep(1)
    
    ret, frame = cap.read()
    
    if ret:
        cv2.imwrite(percorso_temp, frame)
        print("Foto scattata e salvata con successo!")
    else:
        print("[ERRORE] Impossibile leggere il frame dalla fotocamera.")
        percorso_temp = None

    cap.release()
    
    return percorso_temp

def invia_dati_emergenza(client):
    """Carica la foto sul server Flask del PC e invia il payload MQTT all'IA"""
    foto_path = scatta_foto()
    if not foto_path or not os.path.exists(foto_path):
        return

    try:
        print("Caricamento immagine sul server...")
        with open(foto_path, 'rb') as f:
            res = requests.post(STORAGE_UPLOAD_URL, files={'file': f})
        
        url_img = res.json().get("immagine_url").replace(IP_INFRASTRUTTURA, "storage")
        
        payload = {
            "id_dispositivo": DEVICE_ID,
            "nome_dispositivo": NOME,
            "tipo_dispositivo": TIPO,
            "posizione": {
                "nome_zona": ZONA, 
                "coordinate": {"latitudine": 37.5145, "longitudine": 15.0927}
            },
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "dato_rilevato": {
                "allarme": "emergenza_visiva", 
                "dettaglio": "Ispezione visiva live generata dalla Raspberry Pi"
            },
            "immagine_url": url_img
        }
        
        topic_sensore = f"smartcity/sensori/{ZONA}/{TIPO}"
        client.publish(topic_sensore, json.dumps(payload))
        print(f"Payload visivo inviato all' AI! URL: {url_img}")
        
    except Exception as e:
        print(f"[ERRORE RETE] Impossibile comunicare con il PC: {e}")

def elabora_comando(client, payload):
    """Intercetta gli ordini MQTT diretti a questo dispositivo"""
    comando = payload.get("comando")
    if comando == "RICHIEDI_DATO_EMERGENZA":
        print(f"\nRicevuto ordine dal Router AI! Motivo: {payload.get('motivo')}")
        invia_dati_emergenza(client)

def on_message(client, userdata, msg):
    """Callback di ascolto MQTT"""
    try:
        payload = json.loads(msg.payload.decode())
        elabora_comando(client, payload)
    except Exception as e:
        print(f"Errore parsing JSON in arrivo: {e}")

def loop_heartbeat(client):
    """Segnala continuamente alla Dashboard che la Raspberry è viva"""
    topic_hb = f"smartcity/heartbeat/{ZONA}/{TIPO}"
    while True:
        payload = {
            "id_dispositivo": DEVICE_ID,
            "nome_dispositivo": NOME,
            "tipo_dispositivo": TIPO,
            "is_mobile": False,
            "specializzazioni": ["ispezione_visiva"],
            "posizione": {"nome_zona": ZONA, "coordinate": {"latitudine": 37.5145, "longitudine": 15.0927}},
            "stato": "attivo"
        }
        client.publish(topic_hb, json.dumps(payload))
        time.sleep(3)

if __name__ == '__main__':
    print("========================================")
    print(" RASPBERRY PI - CAMERA NODO IoT ATTIVO")
    print("========================================")
    
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    
    print(f"Connessione al Broker MQTT su {IP_INFRASTRUTTURA}...")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)
    
    client.subscribe(f"smartcity/comandi/{DEVICE_ID}")
    
    threading.Thread(target=loop_heartbeat, args=(client,), daemon=True).start()
    
    print("In ascolto di comandi dall'Orchestratore...")
    client.loop_forever()