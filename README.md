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

### Cambio del Modello AI (Edge vs Cloud)
Il sistema supporta l'esecuzione ibrida. Per cambiare il modello in uso, apri il file `AI_Orchestrator.py` e modifica la variabile `MODELLO_ATTIVO`:
- `MODELLO_ATTIVO = "LLAMA_3B_LOCALE"` (Esecuzione Edge su Ollama)
- `MODELLO_ATTIVO = "QWEN_3B_LOCALE"` (Esecuzione Edge su Ollama)
- `MODELLO_ATTIVO = "GPT_20B_CLOUD"` (Esecuzione Cloud tramite API)

*Nota: Se utilizzi un modello Cloud, assicurati di aver inserito le relative API Key (es. GROQ_API_KEY) nel file `.env`.*

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

## 3.1. Visualizzazione della Dashboard Real-Time
Una volta avviati i container, la Dashboard interattiva del Digital Twin sarà disponibile via web.
Apri il browser e collegati a:
 **http://localhost:8080**

Qui potrai monitorare in tempo reale lo stream dei log, la posizione dei dispositivi mobili (droni) e i trigger circolari sulla mappa quando l'Orchestratore decreta lo stato di CRITICO.

## 3.2. Esportazione Allarmi (CAP 1.2)
Quando il nodo Comandante conferma un'emergenza, genera in automatico un file XML aderente allo standard CAP-IT 1.2. I file XML generati vengono salvati sulla macchina Host (fuori dal container) nella cartella:
`./Alerts_CAP/`

## 4. Test e Simulazione Interattiva (Flotta IoT)

Per testare la reazione della Macchina a Stati e dell'AI, il progetto include una flotta completa di dispositivi IoT simulati (telecamere, sensori ambientali e droni) pre-configurati.

### 4.1 Avvio della Flotta IoT
Apri un nuovo terminale, naviga nella cartella di test e avvia tutti i dispositivi in background (\`detached mode\`):
```bash
cd Logica_di_Test
docker-compose up -d
```

### 4.2 Innescare le Emergenze (Interazione con i container)
I dispositivi simulati sono programmati per attendere un input manuale. Poiché sono eseguiti in background all'interno di container Docker, puoi interagire con le loro console utilizzando il comando docker attach.

Scenario A: Innescare un'emergenza da un sensore acustico (Senza immagini)
Collegati al terminale del microfono ambientale:

```bash
docker attach logicaditest-mic_ambientale-1
```
Una volta dentro, premi semplicemente INVIO. Il sensore invierà un allarme
Sulla dashboard potrai osservare l'AI Orchestrator che, non avendo evidenze visive, metterà la zona in stato di ANOMALIA e ordinerà a una telecamera vicina o a un drone di indagare.
Per staccarti dal terminale senza spegnere il sensore, usa la combinazione di tasti: Ctrl+P seguito da Ctrl+Q.

Scenario B: Risoluzione o Conferma tramite Telecamera
Collegati al terminale di una telecamera fissa o di un drone:
```bash
docker attach logicaditest-telecamera_fissa_1-1
```

Digita 1 per innescare o confermare un'emergenza (il nodo ti chiederà di selezionare un'immagine dalla cartella Data_Pool/Telecamere/CRITICO).
Digita 2 per decretare il cessato allarme o un falso allarme (selezionando un'immagine dalla cartella NORMALE).
Il sistema processerà l'immagine tramite il Vision Language Model e, in base al risultato visivo, il Nodo Comandante deciderà se dispiegare i droni (inviando le coordinate GPS tattiche) o ripristinare la normalità.

## 5. Arresto del Sistema

Per spegnere in sicurezza l'architettura, premi CTRL+C nel terminale di Docker Compose.
Per rimuovere definitivamente i container e liberare la rete, esegui:

```bash
docker-compose down
```
