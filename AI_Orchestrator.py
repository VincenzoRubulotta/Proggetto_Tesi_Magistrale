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
import ollama
from langgraph.graph import StateGraph, END
from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
import redis
from concurrent.futures import ThreadPoolExecutor
from memoria import MemoriaSpazioTemporale
from registro import RegistroDispositivi

# --- CONFIGURAZIONI INIZIALI ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
load_dotenv()
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC_IN = os.getenv("MQTT_TOPIC_IN", "smartcity/sensori/#")

llm = OllamaLLM(model="llama3.2", base_url="http://localhost:11434", format="json")
vlm = ChatOllama(model="moondream", base_url="http://localhost:11434")
gestore_memoria = MemoriaSpazioTemporale(finestra_secondi=10)
gestore_registro = RegistroDispositivi(timeout_secondi=300)

# --- PROMPT DEL NODO 1 ---
template_smart_city = """Sei il Cervello Analitico del Digital Twin di una Smart City.
Stai monitorando la zona urbana: {nome_zona}.

Ecco gli eventi IoT registrati negli ultimi 10 secondi:
{contesto_eventi}

DISPOSITIVI ATTUALMENTE ONLINE E DISPONIBILI:
{dispositivi_attivi}

IL TUO OBIETTIVO LOGICO:
Valuta gli eventi seguendo questa rigorosa gerarchia di priorità:
1. EMERGENZA CONFERMATA: Se i dati forniscono una prova inequivocabile di un'emergenza (es. "INCIDENTE_GRAVE", fiamme, blocco stradale), non hai alcun vuoto sensoriale. Imposta lo stato_zona su "CRITICO", il livello_confidenza su "ALTO" e richiedi "NESSUNO".
2. VUOTO SENSORIALE: Se rilevi un'anomalia ambigua, abbassa la confidenza a "MEDIO" o "BASSO" e richiedi esplicitamente l'ID di un ALTRO dispositivo online per verificare.
3. SENSORI ESAURITI: Se hai già dati provenienti da più sensori diversi (es. sia telecamera che microfono) e c'è ancora un'anomalia, DEVI prendere una decisione. Imposta il livello_confidenza su "ALTO" e richiedi "NESSUNO" per sbloccare l'intervento dei soccorsi.

Rispondi ESCLUSIVAMENTE in formato JSON usando questa esatta struttura:
{{
    "stato_zona": "NORMALE" oppure "ANOMALIA" oppure "CRITICO",
    "livello_confidenza": "ALTO", "MEDIO" o "BASSO",
    "motivazione_analisi": "Spiega cosa hai rilevato e perché",
    "tipo_dispositivo_richiesto": "Scrivi il tipo di dispositivo che vuoi usare per colmare il vuoto (es. telecamera). Scrivi NESSUNO se la confidenza è ALTA.",
    "id_dispositivo_richiesto": "Scrivi l'ID ESATTO del dispositivo scelto tra quelli ONLINE (es. ID_CAM_001). Scrivi NESSUNO se non serve nulla."
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
                
                print("[VLM] Download completato. Risveglio Moondream per l'analisi visiva...")
                
                risposta_vlm = ollama.chat(
                    model='moondream',
                    messages=[{
                        'role': 'user',
                        'content': 'Sei un analista di sicurezza urbano. Descrivi brevemente cosa vedi in questa immagine. Ci sono situazioni di pericolo, incidenti o armi?',
                        'images': [image_b64] 
                    }]
                )
                
                descrizione_visiva = risposta_vlm['message']['content'].strip()
                print(f"👁️ [VLM] Report Visivo Generato: {descrizione_visiva}")
                
                evento["analisi_telecamera_vlm"] = descrizione_visiva
                
                break
                
            except requests.exceptions.RequestException as e:
                print(f"[VLM] Errore nel download dell'immagine remota: {e}")
            except Exception as e:
                print(f"[VLM] Errore durante l'analisi visiva: {e}")
    try:
        risultato = analisi_chain.invoke({
            "nome_zona": state["zona"],
            "contesto_eventi": json.dumps(state["contesto_eventi"], ensure_ascii=False),
            "dispositivi_attivi": "\n".join(state["dispositivi_attivi"]) if state["dispositivi_attivi"] else "Nessun dispositivo disponibile."
        })
        print(f"Esito: {risultato.get('stato_zona')} (Confidenza: {risultato.get('livello_confidenza')})")

        state["analisi_json"] = risultato 
    except Exception as e:
        print(f"[ERRORE LLM]: {e}")
        state["analisi_json"] = {"stato_zona": "ERRORE", "livello_confidenza": "BASSO"}
    return state

def decide_dopo_router(state: SmartCityState) -> Any:
    analisi = state.get("analisi_json", {})
    if analisi.get("livello_confidenza") == "ALTO":
        return "comandante"
    return END
  
def nodo_router(state: SmartCityState) -> SmartCityState:
    print(f"\n[NODO 2: ROUTER] Ricerca dati supplementari in corso...")
    zona = state["zona"]
    analisi = state.get("analisi_json") or {}
    
    dato_mancante = analisi.get("tipo_dispositivo_richiesto")

    tipo_richiesto = str(dato_mancante).lower() if dato_mancante else "nessuno"
    id_richiesto = str(analisi.get("id_dispositivo_richiesto", "nessuno")).strip()

    # Protocollo Escalation
    chiave_escalation = f"smartcity:escalation:{zona}"
    tentativi_dubbio = gestore_registro.r.incr(chiave_escalation)
    gestore_registro.r.expire(chiave_escalation, 60)
    
    if tentativi_dubbio >= 3:
        print("[ESCALATION] Troppi tentativi falliti! Vado in emergenza!")
        analisi["livello_confidenza"] = "ALTO" 
        return state
    
    if id_richiesto.lower() in ["nessuno", "null", "none"] and analisi.get("livello_confidenza") in ["MEDIO", "BASSO"]:
        print("L'IA è incerta ma ha esaurito i sensori da chiamare. Forzo l'Escalation al Comandante!")
        analisi["livello_confidenza"] = "ALTO" 
        return state

    if id_richiesto.lower() not in ["nessuno", "null", "none"]:
        target_trovato = None
        for disp in state["dispositivi_attivi"]:
            if id_richiesto in disp:
                target_trovato = id_richiesto
                break
        
        if target_trovato:
            print(f"Trovato {target_trovato}. Invio comando MQTT!")
            topic = f"smartcity/comandi/{target_trovato}"
            payload = json.dumps({
                "comando": "RICHIEDI_DATO_EMERGENZA", 
                "motivo": analisi.get("motivazione_analisi", "Motivo non specificato")
            })
            client_pub.publish(topic, payload) 
        else:
            print(f"Nessun sensore di tipo '{tipo_richiesto}' attivo.")
    else:
        print("⏸L'IA non ha richiesto dati supplementari.")
        
    return state

def nodo_comandante(state: SmartCityState) -> SmartCityState:
    print(f"\n[NODO 3: COMANDANTE] Intervento di Emergenza Richiesto per {state['zona']}!")
    gestore_registro.r.delete(f"smartcity:escalation:{state['zona']}")
    print("Qui configureremo il secondo LLM per decidere l'azione finale.")
    return state

# 3. Router Logic)
def decide_prossimo_nodo(state: SmartCityState) -> str:
    analisi = state.get("analisi_json", {})
    stato_zona = analisi.get("stato_zona", "NORMALE")
    confidenza = analisi.get("livello_confidenza", "ALTO")
    
    if stato_zona == "NORMALE":
        return "fine"
    if stato_zona in ["ANOMALIA", "CRITICO"]:
        if confidenza in ["BASSO", "MEDIO"]:
            return "router"
        elif confidenza == "ALTO":
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
workflow.add_conditional_edges("router", decide_dopo_router)

app_smart_city = workflow.compile()

r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

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
        risultato_redis = r.blpop("smartcity:coda_lavori", timeout=0) 
        
        if risultato_redis:
            _, payload_stringa = risultato_redis
            stato_iniziale = json.loads(payload_stringa)
            
            executor.submit(esegui_grafo, stato_iniziale)
            
except KeyboardInterrupt:
    print("\nSpegnimento AI Orchestrator in corso...")
    executor.shutdown(wait=True)
    client_pub.loop_stop()
    client_pub.disconnect()



