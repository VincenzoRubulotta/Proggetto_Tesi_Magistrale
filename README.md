```plaintext
/PROGETTO_TESI_MAGISTRALE
├── dashboard/             # App Flask/Leaflet per la visualizzazione Real-Time della mappa
├── Logica_di_Test/        # Script per la simulazione deterministica End-to-End
│   ├── Data_Pool/         # Immagini di test (CRITICO/NORMALE) per l'analisi visiva (VLM)
│   └── device_node.py     # Simulatore interattivo dei dispositivi IoT
├── .env                   # Variabili d'ambiente (configurazioni LangChain, porte, ecc.)
├── docker-compose.yml     # Configurazione per l'orchestrazione dei 6 servizi containerizzati
├── Dockerfile             # Istruzioni per la build dell'immagine Python di backend
├── Gateway_IoT.py         # Microservizio: Intercetta i sensori MQTT e scrive su buffer Redis
├── Storage_Immagini.py    # Microservizio: Server Flask locale per upload/download foto
├── AI_Orchestrator.py     # Microservizio: Cervello AI con LangGraph (Investigatore, Router, Comandante)
├── prompts.py             # Modulo: Centralizzazione dei template di Prompt Engineering
├── utils.py               # Modulo: Helper per calcolo distanze GPS, parsing visivo (VLM) e formattazione
├── memoria.py             # Modulo: Gestione della finestra spazio-temporale degli eventi su Redis
├── registro.py            # Modulo: Mappatura, Heartbeat e distanze dei dispositivi IoT
└── schema.py              # Modelli dati Pydantic per la validazione dello scudo input
```


## 1. Prerequisiti (Host Machine)
Prima di avviare l'infrastruttura Docker, assicurati di avere i seguenti servizi installati e configurati sul tuo PC fisico (Host).


###  A. Mosquitto (broker Mqtt)
Assicurati che il demone Mosquitto sia installato e in esecuzione:

```bash
sudo apt install mosquitto mosquitto-clients
sudo systemctl start mosquitto 
```


### B. Ollama (AI Engine)

Devi aver installato Ollama e scaricato i modelli necessari:

```bash
ollama pull llama3.2
ollama pull moondream
```

Configurazione Fondamentale per Docker (Linux):
Poiché Ollama deve comunicare con i container Docker, devi abilitare l'ascolto su tutte le interfacce di rete.

Modifica il servizio:

```bash
sudo systemctl edit ollama.service

Aggiungi queste righe in cima:

Ini, TOML
[Service]
Environment="OLLAMA_HOST=0.0.0.0"

sudo systemctl daemon-reload && sudo systemctl restart ollama
```
### C. Docker e Docker Compose

Assicurati di avere Docker e il plugin docker-compose installati sul tuo sistema.

## 2. Configurazione dell'Ambiente

Crea un file chiamato .env nella root del progetto (la stessa cartella del docker-compose.yml) e inserisci le seguenti variabili d'ambiente:

## --- FILE .env ---
```bash
# Configurazione MQTT
# Su Linux, host.docker.internal permette al container di vedere il Mosquitto dell'Host
MQTT_BROKER=host.docker.internal
MQTT_PORT=1883
MQTT_TOPIC_IN=smartcity/sensori/#

# Configurazione Redis (Riferimenti interni alla rete Docker)
REDIS_HOST=redis-db
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Configurazione Orchestratore
WORKERS_COUNT=3

# Configurazione Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2

#Configurazione LANGCHAIN
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT="https://api.smith.langchain.com"
LANGCHAIN_API_KEY= "Tua APi Key"
LANGCHAIN_PROJECT= "Tuo Progetto"
```


## 3. Deploy del Sistema (Docker Compose)

Il deploy dell'infrastruttura avviene in un solo comando grazie a Docker Compose, che costruirà le immagini Python e collegherà i 4 servizi (Gateway, Orchestrator, Storage, Redis) nella stessa rete virtuale.

Nel terminale, naviga nella cartella del progetto ed esegui:

```bash
docker-compose up --build
```
## 4. Arresto del Sistema
Per spegnere in sicurezza, vai nel terminale  premi CTRL+C.
Per rimuovere definitivamente i container esegui:

```bash
docker-compose down
```