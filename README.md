```plaintext
/PROGGETTO_TESI_MAGISTRALE
├── .env                   # Variabili d'ambiente (configurazioni MQTT, Redis, LangChain, ecc.)
├── docker-compose.yml     # Configurazione dei 4 servizi containerizzati e delle reti
├── Dockerfile             # Istruzioni per la build dell'immagine Python universale
├── requirements.txt       # Dipendenze del progetto (MQTT, LangChain, Flask, Redis, ecc.)
├── Gateway_IoT.py         # Microservizio 1: Intercetta i sensori MQTT e scrive su Redis
├── Storage_Immagini.py    # Microservizio 2: Server Flask per upload/download file locali
├── AI_Orchestrator.py     # Microservizio 3: Cervello AI con LangGraph, Llama 3.2 e Moondream
├── memoria.py             # Modulo condiviso: Gestione della memoria spazio-temporale
├── registro.py            # Modulo condiviso: Mappatura dei dispositivi IoT attivi
├── schema.py              # Modelli dati Pydantic per la validazione degli input
└── README.md              # Questo file di documentazione
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

⚠️ Configurazione Fondamentale per Docker (Linux):
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
## 5. Arresto del Sistema

Per spegnere in sicurezza la Smart City, vai nel terminale "Cabina di Regia" e premi CTRL+C. I container riceveranno il segnale di terminazione, chiuderanno le connessioni e Redis salverà lo snapshot finale sul disco.

Per rimuovere definitivamente i container arrestati, esegui:

```bash
docker-compose down
```