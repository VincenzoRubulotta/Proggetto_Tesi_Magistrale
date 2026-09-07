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
L'infrastruttura di backend e i broker (MQTT, Redis) sono interamente containerizzati. L'unico componente AI che deve girare nativamente sulla macchina Host (sfruttando l'accelerazione hardware/GPU) è Ollama.


###  A. Ollama
Devi aver installato Ollama sul tuo PC fisico e scaricato i modelli necessari:

```bash
ollama pull llama3.2
ollama pull moondream
```

Configurazione Fondamentale per Docker:
Poiché Ollama deve comunicare con i container Docker virtuali, devi abilitare l'ascolto su tutte le interfacce di rete. Modifica il servizio di sistema:

```bash
sudo systemctl edit ollama.service
```

Aggiungi queste righe nel file di override:

```bash
[Service]
Environment="OLLAMA_HOST=0.0.0.0"
```

Riavvia il daemon:

```bash
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

### B. Docker e Docker Compose

Assicurati di avere Docker e il plugin docker-compose installati.
(Nota: Assicurati che non vi siano installazioni locali di Redis o Mosquitto in esecuzione sull'Host per evitare conflitti sulle porte 6379 e 1883).


## 2. Configurazione dell'Ambiente

Crea un file chiamato .env nella root del progetto e inserisci le seguenti variabili d'ambiente.
(Nota: i nomi host come mqtt o redis vengono automaticamente sovrascritti dal docker-compose.yml all'interno della rete virtuale).

## --- FILE .env ---
```bash
# Configurazione Host Esterni (Per test locali senza Docker)
MQTT_BROKER=localhost
MQTT_PORT=1883
MQTT_TOPIC_IN=smartcity/sensori/#

REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=

# Configurazione Orchestratore
WORKERS_COUNT=3

# Configurazione Ollama (host.docker.internal punta al localhost dell'Host Machine)
OLLAMA_BASE_URL=[http://host.docker.internal:11434](http://host.docker.internal:11434)
OLLAMA_MODEL=llama3.2

# Configurazione Tracciabilità LangSmith (Opzionale ma raccomandata)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT="[https://api.smith.langchain.com](https://api.smith.langchain.com)"
LANGCHAIN_API_KEY="Tua_API_Key"
LANGCHAIN_PROJECT="SmartCity_DigitalTwin"
```


## 3. Deploy del Sistema (Docker Compose)

l deploy dell'intera infrastruttura avviene con un singolo comando. Docker Compose avvierà 6 servizi interconnessi nella rete smartcity_net:
MQTT Broker (Mosquitto)
Database (Redis)
Storage Immagini (Flask)
Gateway IoT
AI Orchestrator
Dashboard Web
Nel terminale, naviga nella cartella root del progetto ed esegui:

```bash
docker-compose up --build
```
## 4. Test e Simulazione (Logica_di_Test)
Per testare la reazione della Macchina a Stati e dell'AI, apri un nuovo terminale, assicurati di avere le dipendenze installate, e avvia il simulatore dei sensori:

```bash
cd Logica_di_Test
python device_node.py
```

Usa il menu interattivo nel terminale del dispositivo per innescare l'emergenza (1) o decretare il cessato allarme inviando i dati di ripristino (2).

## 5. Arresto del Sistema

Per spegnere in sicurezza l'architettura, premi CTRL+C nel terminale di Docker Compose.
Per rimuovere definitivamente i container e liberare la rete, esegui:

```bash
docker-compose down
```
