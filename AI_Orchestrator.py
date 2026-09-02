import os
import json
import time
import queue
import threading
import logging
from typing import Any
from typing import TypedDict, List, Dict, Any, Optional
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
import base64
from langchain_core.messages import HumanMessage
import requests
from langchain_ollama import ChatOllama
import ollama
from langgraph.graph import StateGraph, END
from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
import redis
from concurrent.futures import ThreadPoolExecutor
from memoria import MemoriaSpazioTemporale
from registro import RegistroDispositivi
from langchain_core.output_parsers import JsonOutputParser

# --- CONFIGURAZIONI INIZIALI ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC_IN = os.getenv("MQTT_TOPIC_IN", "smartcity/sensori/#")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

json_parser = JsonOutputParser()
llm = OllamaLLM(model="llama3.2", base_url="http://host.docker.internal:11434", format="json")
vlm = ChatOllama(model="moondream", base_url="http://host.docker.internal:11434")
gestore_memoria = MemoriaSpazioTemporale(host=REDIS_HOST, port=REDIS_PORT, finestra_secondi=120)
gestore_registro = RegistroDispositivi(host=REDIS_HOST, port=REDIS_PORT, timeout_secondi=300)

# --- PROMPT DEL NODO 1 ---
template_smart_city = """Sei il Cervello Analitico del Digital Twin di una Smart City.
Stai monitorando la zona urbana: {nome_zona}.

Ecco il resoconto degli eventi IoT registrati negli ultimi 120 secondi:
{contesto_eventi}

DISPOSITIVI ATTUALMENTE ONLINE E DISPONIBILI:
{dispositivi_attivi}

IL TUO OBIETTIVO LOGICO:
Valuta gli eventi seguendo queste REGOLE ASSOLUTE:

1. TRADUZIONE OBBLIGATORIA: Le descrizioni visive (VLM) sono in INGLESE. Devi prima tradurle mentalmente in italiano e focalizzarti sui fatti.
2. RISPETTO DELLA REALTÀ DEI DATI: Non inventare MAI descrizioni visive o interventi di droni/telecamere se nel campo {contesto_eventi} non è presente un URL di immagine reale o un'analisi VLM associata. Se ci sono solo dati di microfoni o sensori ambientali, basa le tue deduzioni unicamente su di essi.
3. TOLLERANZA ZERO SULL'AMBIGUITÀ: Se nelle descrizioni visive leggi chiaramente di veicoli in fiamme ('fire', 'flames', 'engulfed') o incidenti gravi ('crushed', 'accident', 'debris'), la situazione NON è ambigua. È un'emergenza reale.
4. EMERGENZA CONFERMATA: Se c'è evidenza visiva di incidente o incendio, ignora eventuali discrepanze di altri sensori. Imposta IMMEDIATAMENTE stato_zona su "CRITICO", confidenza su "ALTO" e id_dispositivo_richiesto su "NESSUNO".
5. SMENTITA FALSO ALLARME: Se i sensori segnalano un'anomalia, ma l'analisi visiva descrive esplicitamente una situazione tranquilla, imposta stato_zona su "NORMALE".
6. OBBLIGO DI ISPEZIONE IN CONTESTO AMBIGUO: Se la situazione non è chiara (es. allarme acustico senza immagini), DEVI impostare la confidenza su "MEDIO" e obbligatoriamente indicare un ID valido di una telecamera o drone presente nella lista dei dispositivi attivi nei campi "tipo_dispositivo_richiesto" e "id_dispositivo_richiesto". NON scrivere mai "NESSUNO" se la confidenza è media o bassa.

Rispondi ESCLUSIVAMENTE in formato JSON usando questa esatta struttura ordinata (NON USARE MAI `null`):
{{
    "traduzione_e_fatti": "Traduci brevemente in italiano le descrizioni visive ed elenca i fatti nudi e crudi.",
    "pericoli_rilevati": ["elenco", "dei", "pericoli", "rilevati", "oppure vuoto se nessuno"],
    "stato_zona": "Inserisci esattamente uno di questi tre valori: NORMALE, ANOMALIA oppure CRITICO",
    "livello_confidenza": "Inserisci esattamente uno di questi tre valori: ALTO, MEDIO oppure BASSO",
    "motivazione_analisi": "Spiegazione basata ESCLUSIVAMENTE sui fatti appena elencati.",
    "tipo_dispositivo_richiesto": "Se la confidenza è MEDIO o BASSO, scrivi il tipo di un dispositivo scegliendolo dalla lista 'DISPOSITIVI ATTUALMENTE ONLINE'. Se ALTO scrivi NESSUNO.",
    "id_dispositivo_richiesto": "Se la confidenza è MEDIO o BASSO, COPIA QUI l'ID ESATTO di un dispositivo dalla lista 'DISPOSITIVI ATTUALMENTE ONLINE' (non scegliere lo stesso sensore che ha generato l'evento). VIETATO scrivere NESSUNO se sei incerto!"
}}
"""
prompt = PromptTemplate(template=template_smart_city, input_variables=["nome_zona", "contesto_eventi", "dispositivi_attivi"])
analisi_chain = prompt | llm | JsonOutputParser()

client_pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client_pub.connect(MQTT_BROKER, MQTT_PORT, 60)
client_pub.loop_start()

# ==========================================================
# ARCHITETTURA LANGGRAPH: LO STATO E I NODI
# ==========================================================

# 1. (State)
class SmartCityState(TypedDict):
    zona: str
    contesto_eventi: List[Dict[str, Any]]
    dispositivi_attivi: List[str]
    analisi_json: Optional[Dict[str, Any]]

# 2. I NODI (Workers)
def nodo_investigatore(state: SmartCityState) -> SmartCityState:
    print(f"\n[NODO 1: INVESTIGATORE] Analizzo la zona: {state['zona']}")

    contesto = state["contesto_eventi"]
    for evento in contesto:
        if "immagine_url" in evento and evento["immagine_url"]:
            print(f"[VLM] Rilevato URL Immagine Remota nell'evento del sensore {evento.get('id_dispositivo')}! Inizio download...")
            url_immagine = evento["immagine_url"]
            
            try:
                risposta_http = requests.get(url_immagine, timeout=5)
                risposta_http.raise_for_status()
                
                image_b64 = base64.b64encode(risposta_http.content).decode("utf-8")
                print("[VLM] Download completato. Risveglio Moondream per l'analisi visiva...")
                
                # Creiamo il messaggio per LangChain usando l'inglese per aiutare Moondream
                messaggio = HumanMessage(
                    content=[
                        {"type": "text", "text": "You are a security analyst. Describe exactly what you see in this image. Are there any accidents, hazards, vehicles, or people?"},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                    ]
                )
                
                # Invochiamo il VLM tramite LangChain (così LangSmith traccia tutto!)
                risposta_vlm = vlm.invoke([messaggio])
                
                # Estraiamo il contenuto testuale
                descrizione_visiva = risposta_vlm.content.strip()
                print(f"[VLM] Report Visivo Generato: {descrizione_visiva}")
                
                evento["analisi_telecamera_vlm"] = descrizione_visiva
                
                
            except requests.exceptions.RequestException as e:
                print(f"[VLM] Errore nel download dell'immagine remota: {e}")
            except Exception as e:
                print(f"[VLM] Errore durante l'analisi visiva: {e}")
    try:
        eventi_testo_pulito = ""
        for ev in state["contesto_eventi"]:
            eventi_testo_pulito += f"- Dispositivo: {ev.get('nome_dispositivo', 'Sconosciuto')} ({ev.get('tipo_dispositivo', 'Sconosciuto')})\n"
            if "analisi_telecamera_vlm" in ev:
                eventi_testo_pulito += f"  Analisi Visiva (VLM): {ev['analisi_telecamera_vlm']}\n"
            if "dato_rilevato" in ev:
                eventi_testo_pulito += f"  Dato Sensore: {ev['dato_rilevato']}\n"
            eventi_testo_pulito += "\n"
        
        print(f"\n[DEBUG INVESTIGATORE] Dispositivi attivi passati all'LLM: {state['dispositivi_attivi']}")

        risultato = analisi_chain.invoke({
            "nome_zona": state["zona"],
            "contesto_eventi": json.dumps(state["contesto_eventi"], ensure_ascii=False),
            "dispositivi_attivi": "\n".join(state["dispositivi_attivi"]) if state["dispositivi_attivi"] else "Nessun dispositivo disponibile."
        })
        print(f"[DEBUG INVESTIGATORE] Risposta grezza LLM (Analisi JSON): {risultato}")
        print(f"Esito: {risultato.get('stato_zona')} (Confidenza: {risultato.get('livello_confidenza')})")

        state["analisi_json"] = risultato 
    except Exception as e:
        print(f"[ERRORE LLM]: {e}")
        state["analisi_json"] = {"stato_zona": "ERRORE", "livello_confidenza": "BASSO"}
    return state
  
def nodo_router(state: SmartCityState) -> SmartCityState:
    print(f"\n[NODO 2: ROUTER] Ricerca dati supplementari in corso...")
    zona = state["zona"]
    analisi = state.get("analisi_json") or {}
    
    dato_mancante = analisi.get("tipo_dispositivo_richiesto")

    tipo_richiesto = str(dato_mancante).lower() if dato_mancante else "nessuno"
    id_richiesto = str(analisi.get("id_dispositivo_richiesto", "nessuno")).strip()

    print(f"[DEBUG ROUTER] L'IA ha chiesto il tipo: '{tipo_richiesto}' con ID esatto: '{id_richiesto}'")
    print(f"[DEBUG ROUTER] Dispositivi disponibili nello stato: {state.get('dispositivi_attivi')}")

    # Protocollo Escalation
    chiave_escalation = f"smartcity:escalation:{zona}"
    tentativi_dubbio = gestore_registro.r.incr(chiave_escalation)
    gestore_registro.r.expire(chiave_escalation, 60)
    
    if tentativi_dubbio >= 3:
        print("[ESCALATION] Troppi tentativi falliti! Vado in emergenza!")
        analisi["livello_confidenza"] = "ALTO" 
        return state
    
    if id_richiesto.lower() in ["nessuno", "null", "none", ""] and analisi.get("livello_confidenza") in ["MEDIO", "BASSO"]:
        print("L'IA è incerta ma ha esaurito i sensori da chiamare. Forzo l'Escalation al Comandante!")
        analisi["livello_confidenza"] = "ALTO" 
        return state

    if id_richiesto.lower() not in ["nessuno", "null", "none", ""]:
        target_trovato = None
        id_pulito = None

        for disp in state["dispositivi_attivi"]:
            if id_richiesto.upper() in disp.upper():
                target_trovato = disp
                id_pulito = disp.split(" ")[0].strip()
                break
        
        if target_trovato and id_pulito:
            print(f"Trovato {id_pulito}. Invio comando MQTT!")
            topic = f"smartcity/comandi/{id_pulito}"
            payload = json.dumps({
                "comando": "RICHIEDI_DATO_EMERGENZA", 
                "motivo": analisi.get("motivazione_analisi", "Motivo non specificato")
            })
            client_pub.publish(topic, payload) 
        else:
            print(f"Nessun sensore corrispondente a '{id_richiesto}' trovato tra quelli attivi.")
            analisi["livello_confidenza"] = "ALTO"
        
    return state

def nodo_comandante(evento):
    """
    Nodo 3: COMANDANTE
    Legge il report, valuta le risorse IoT disponibili e decide l'intervento tattico.
    Se non c'è reale pericolo, annulla l'emergenza per non sprecare risorse.
    """
    zona = evento.get("zona", "Sconosciuta")
    contesto_eventi = evento.get("contesto_eventi", [])
    analisi = evento.get("analisi_json", {})
    dispositivi_attivi = evento.get("dispositivi_attivi", [])
    
    coordinate = "Non specificate"
    if contesto_eventi and "posizione" in contesto_eventi[0]:
        coord = contesto_eventi[0]["posizione"].get("coordinate")
        if coord:
            coordinate = f"Latitudine: {coord.get('latitudine')}, Longitudine: {coord.get('longitudine')}"

    print(f"\n[NODO 3: COMANDANTE] Valutazione Intervento Strategico per {zona}...")
    
    prompt_comandante = f"""Sei il Comandante Operativo delle Forze di Sicurezza e Soccorso della Smart City.
Stai valutando una potenziale emergenza.

DATI DELL'EVENTO:
- Zona: {zona}
- Coordinate GPS: {coordinate}

REPORT DELL'INVESTIGATORE AI:
- Motivazione e Contesto Visivo: {analisi.get('motivazione_analisi', 'Nessuna descrizione')}

DISPOSITIVI TATTICI ONLINE (DISPONIBILI IN ZONA/LIMITROFI):
{dispositivi_attivi}

IL TUO OBIETTIVO STRATEGICO E TATTICO:
1. VALUTAZIONE GRAVITÀ: Analizza il report. C'è un pericolo reale? O si tratta di un falso allarme / situazione innocua? Il tuo dovere è NON sprecare risorse pubbliche.
2. FORZE UMANE: Se l'intervento è strettamente necessario, scegli chi dispiegare tra ["POLIZIA", "AMBULANZA", "VIGILI_DEL_FUOCO", "PROTEZIONE_CIVILE"]. Se la situazione NON richiede intervento, scrivi "NESSUNO".
3. SUPPORTO CYBER-FISICO: Se mandi unità umane, dirotta i dispositivi (es. DRONE) per supporto. Se NON mandi unità umane, puoi usare un drone per un controllo passivo di routine, oppure scrivere "NESSUNO" per chiudere totalmente il caso.

Rispondi ESCLUSIVAMENTE in formato JSON con questa esatta struttura:
{{
    "unita_intervento_umano": ["Elenco delle forze da inviare. Scrivi NESSUNO se non c'è emergenza"],
    "dispositivi_tattici_attivati": ["Elenco ID dispositivi da usare (es. DRONE_POLIZIA_01). Scrivi NESSUNO se non servono"],
    "ordine_operativo": "Messaggio radio per le unità (es. ordini di ingaggio) OPPURE motivazione dell'annullamento (es. 'Nessun intervento richiesto, falso allarme confermato. Chiudere l'incidente.')."
}}
"""
    
    try:
        # Invochiamo il LLM forzando la risposta JSON
        risposta_llm = llm.invoke(prompt_comandante)
        decisione = json_parser.invoke(risposta_llm)
        
        print("\n==================================================")
        print("ORDINE DEL COMANDANTE")
        print(f"Target          : {zona} ({coordinate})")
        print(f"Unità Umane     : {', '.join(decisione.get('unita_intervento_umano', []))}")
        print(f"Supporto IoT    : {', '.join(decisione.get('dispositivi_tattici_attivati', []))}")
        print(f"Messaggio Radio : {decisione.get('ordine_operativo', '')}")
        print("==================================================\n")
        
        evento["ordine_comandante"] = decisione

        dispositivi_attivati = decisione.get("dispositivi_tattici_attivati", [])
        if isinstance(dispositivi_attivati, list):
            for disp_id in dispositivi_attivati:
                if disp_id.lower() not in ["nessuno", "null", "none"]:
                    topic_cmd = f"smartcity/comandi/{disp_id}"
                    payload_cmd = json.dumps({
                        "comando": "DISPIEGAMENTO_TATTICO",
                        "ordine_operativo": decisione.get("ordine_operativo", ""),
                        "zona_target": zona
                    })
                    client_pub.publish(topic_cmd, payload_cmd)
                    print(f"[MQTT] Ordine operativo inviato al dispositivo: {disp_id}")
        
    except Exception as e:
        print(f"[COMANDANTE] Errore critico di dispiegamento: {e}")
        evento["ordine_comandante"] = {"errore": "Impossibile generare l'ordine"}
    
    return evento

# 3. Router Logic)
def decide_prossimo_nodo(state: SmartCityState) -> str:
    analisi = state.get("analisi_json", {})
    stato_zona = analisi.get("stato_zona", "NORMALE")
    confidenza = analisi.get("livello_confidenza", "ALTO")
    
    if confidenza in ["BASSO", "MEDIO"]:
        return "router"
        
    if stato_zona == "NORMALE" and confidenza == "ALTO":
        return "fine"
        
    if stato_zona in ["ANOMALIA", "CRITICO"] and confidenza == "ALTO":
        return "comandante"
        
    return "fine"

def decide_dopo_router(state: SmartCityState) -> str:
    analisi = state.get("analisi_json", {})
    confidenza = analisi.get("livello_confidenza", "ALTO")
    
    if confidenza == "ALTO":
        return "comandante"
    
    return "fine"

# 4. ASSEMBLAGGIO DEL GRAFO
workflow = StateGraph(SmartCityState)
workflow.add_node("investigatore", nodo_investigatore)
workflow.add_node("router", nodo_router)
workflow.add_node("comandante", nodo_comandante)

workflow.set_entry_point("investigatore")
workflow.add_conditional_edges(
    "investigatore",
    decide_prossimo_nodo,
    {
        "router": "router",
        "comandante": "comandante",
        "fine": END
    }
)


workflow.add_edge("comandante", END)
workflow.add_conditional_edges(
    "router",
    decide_dopo_router,
    {
        "comandante": "comandante",
        "fine": END
    }
)

app_smart_city = workflow.compile()

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

NUMERO_WORKER_PARALLELI = 3  
executor = ThreadPoolExecutor(max_workers=NUMERO_WORKER_PARALLELI)

def esegui_grafo(stato_iniziale):
    """Funzione eseguita dal singolo worker nel suo thread separato"""
    print(f"\n[AI CORE] Inizio elaborazione evento per {stato_iniziale['zona']}...")
    try:
        app_smart_city.invoke(stato_iniziale)
    except Exception as e:
        print(f"[ERRORE AI CORE] Crash durante l'esecuzione del grafo: {e}")

print("\nAvvio AI Orchestrator (LangGraph + Llama 3.2)...")
print(f"In ascolto continuo sulla coda Redis 'smartcity:coda_lavori' con {NUMERO_WORKER_PARALLELI} worker...")

try:
    while True:
        risultato_redis = r.blpop("smartcity:coda_lavori", timeout=2) 
        
        if risultato_redis:
            _, payload_stringa = risultato_redis
            stato_iniziale = json.loads(payload_stringa)
            
            executor.submit(esegui_grafo, stato_iniziale)
            
except KeyboardInterrupt:
    print("\nSpegnimento AI Orchestrator in corso...")
    executor.shutdown(wait=True)
    client_pub.loop_stop()
    client_pub.disconnect()



