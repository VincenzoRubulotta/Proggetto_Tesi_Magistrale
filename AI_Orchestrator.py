import os
import json
import time
import queue
import math
import threading
import logging
import base64
from typing import TypedDict, List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

import requests
import redis
import ollama
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from langchain_ollama import ChatOllama, OllamaLLM
from langgraph.graph import StateGraph, END

from memoria import MemoriaSpazioTemporale
from registro import RegistroDispositivi
from prompts import TEMPLATE_INVESTIGATORE, TEMPLATE_CORRETTORE, get_prompt_comandante
from utils import analizza_immagine_vlm, formatta_dispositivi_investigatore, ordina_e_taglia_dispositivi_comandante

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


prompt = PromptTemplate(template=TEMPLATE_INVESTIGATORE, input_variables=["nome_zona", "contesto_eventi", "dispositivi_attivi"])
analisi_chain = prompt | llm | JsonOutputParser()

client_pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client_pub.connect(MQTT_BROKER, MQTT_PORT, 60)
client_pub.loop_start()


# ==========================================================
# ARCHITETTURA LANGGRAPH: LO STATO E I NODI
# ==========================================================

# 1. (State)
class SmartCityState(TypedDict):
    epicentro_id: str
    lat_epicentro: float
    lon_epicentro: float
    contesto_eventi: List[Dict[str, Any]]
    dispositivi_attivi: List[str]
    analisi_json: Optional[Dict[str, Any]]
    raw_text: Optional[str]        
    errore_parsing: Optional[str]

# 2. I NODI (Workers)
def nodo_investigatore(state: SmartCityState) -> SmartCityState:

    epicentro_id = state['epicentro_id']
    lat_evento = state['lat_epicentro']
    lon_evento = state['lon_epicentro']

    print(f"\n[NODO 1: INVESTIGATORE] Analizzo epicentro: {epicentro_id}")

    for evento in state["contesto_eventi"]:
        if "immagine_url" in evento and evento["immagine_url"]:
            print(f"[VLM] Rilevato URL Immagine Remota nell'evento del sensore {evento.get('id_dispositivo')}! Inizio download...")
            descrizione_visiva = analizza_immagine_vlm(evento["immagine_url"], vlm)
            if descrizione_visiva:
                print(f"[VLM] Report Visivo Generato: {descrizione_visiva}")
                evento["analisi_telecamera_vlm"] = descrizione_visiva

    try:
        
        dispositivi_formattati = formatta_dispositivi_investigatore(state["dispositivi_attivi"], lat_evento, lon_evento)

        print(f"\n[DEBUG INVESTIGATORE] Dispositivi attivi passati all'LLM: {state['dispositivi_attivi']}")

        stato_globale = gestore_registro.r.get(f"smartcity:stato_emergenza:{epicentro_id}") or "NORMALE"
        print(f"[DEBUG INVESTIGATORE] Lo stato globale attuale della zona è: {stato_globale}")

        risposta_grezza = (prompt | llm).invoke({
            "coordinate_epicentro": f"{lat_evento}, {lon_evento}",
            "stato_globale": stato_globale,
            "contesto_eventi": json.dumps(state["contesto_eventi"], ensure_ascii=False),
            "dispositivi_attivi": "\n".join(dispositivi_formattati) if dispositivi_formattati else "Nessun dispositivo."
        })
        
        try:
            testo_pulito = risposta_grezza.replace("```json", "").replace("```", "").strip()
            if "{" in testo_pulito and "}" in testo_pulito:
                testo_pulito = testo_pulito[testo_pulito.find("{"):testo_pulito.rfind("}")+1]
                
            risultato = json.loads(testo_pulito)

            # Controllo Cessato Allarme Autonomo
            if risultato.get("stato_zona") == "NORMALE" and stato_globale == "CRITICO":
                gestore_registro.r.set(f"smartcity:stato_emergenza:{epicentro_id}", "NORMALE")
                print(f"\n[STATE MACHINE] L'IA ha decretato il CESSATO ALLARME! La zona {epicentro_id} è di nuovo sicura.")

            stato_valutato = risultato.get("stato_zona", "NORMALE")
            payload_mappa = {
                "epicentro_id": epicentro_id, 
                "lat": lat_evento, 
                "lon": lon_evento, 
                "stato": stato_valutato
            }
            client_pub.publish(f"smartcity/mappa/{epicentro_id}", json.dumps(payload_mappa))

            state["analisi_json"] = risultato
            state["errore_parsing"] = None
            print(f"[DEBUG INVESTIGATORE] Analisi JSON completata con successo.")
            print(f"Esito: {risultato.get('stato_zona')} (Confidenza: {risultato.get('livello_confidenza')})")
            
        except json.JSONDecodeError as e:
            print(f"[ALLARME] L'LLM ha generato un JSON corrotto! Attivo il Nodo Correttore...")
            state["raw_text"] = risposta_grezza
            state["errore_parsing"] = str(e)
            
    except Exception as e:
        print(f"[ERRORE LLM CRITICO]: {e}")
        state["analisi_json"] = {"stato_zona": "ERRORE", "livello_confidenza": "BASSO"}
        
    return state


def nodo_correttore(state: SmartCityState) -> SmartCityState:
    print(f"\n[NODO CORRETTORE] Tento di riparare la formattazione per la zona: {state['epicentro_id']}")
    
    
    prompt_corr = PromptTemplate(template=TEMPLATE_CORRETTORE, input_variables=["errore", "testo_raw"])
    risposta_grezza = (prompt_corr | llm).invoke({
        "errore": state.get("errore_parsing", "Errore JSON generico"),
        "testo_raw": state.get("raw_text", "")
    })
    
    try:
        testo_pulito = risposta_grezza.replace("```json", "").replace("```", "").strip()
        if "{" in testo_pulito and "}" in testo_pulito:
            testo_pulito = testo_pulito[testo_pulito.find("{"):testo_pulito.rfind("}")+1]
            
        risultato = json.loads(testo_pulito)
        state["analisi_json"] = risultato
        state["errore_parsing"] = None
        print("[NODO CORRETTORE] JSON riparato e salvato con successo!")
    except Exception as e:
        print(f"[NODO CORRETTORE] Fallimento irreparabile. Attivo Fallback di emergenza.")
        state["analisi_json"] = {
            "stato_zona": "ANOMALIA",
            "livello_confidenza": "MEDIO",
            "motivazione_analisi": "Errore critico di parsing persistente.",
            "id_dispositivi_richiesti": []
        }
        state["errore_parsing"] = None
        
    return state

def nodo_router(state: SmartCityState) -> SmartCityState:
    print(f"\n[NODO 2: ROUTER] Ricerca dati supplementari in corso...")
    zona = state["epicentro_id"]
    analisi = state.get("analisi_json") or {}
    
    dispositivi_richiesti = analisi.get("id_dispositivi_richiesti", [])
    if isinstance(dispositivi_richiesti, str):
        if dispositivi_richiesti.upper() in ["NESSUNO", "NULL", "NONE", ""]:
            dispositivi_richiesti = []
        else:
            dispositivi_richiesti = [dispositivi_richiesti]

    print(f"[DEBUG ROUTER] L'IA ha richiesto i dispositivi: {dispositivi_richiesti}")

    lat_target, lon_target = None, None
    if state["contesto_eventi"] and "posizione" in state["contesto_eventi"][0]:
        coord = state["contesto_eventi"][0]["posizione"].get("coordinate")
        if coord:
            lat_target, lon_target = coord.get("latitudine"), coord.get("longitudine")

    # Protocollo Escalation
    chiave_escalation = f"smartcity:escalation:{zona}"
    tentativi_dubbio = gestore_registro.r.incr(chiave_escalation)
    gestore_registro.r.expire(chiave_escalation, 60)
    
    if tentativi_dubbio >= 3:
        print("[ESCALATION] Troppi tentativi falliti! Vado in emergenza al Comandante!")
        analisi["livello_confidenza"] = "ALTO" 
        return state
    
    if not dispositivi_richiesti and analisi.get("livello_confidenza") in ["MEDIO", "BASSO"]:
        print("[ESCALATION] L'IA è incerta ma ha esaurito i sensori o l'array è vuoto. Forzo l'Escalation al Comandante!")
        analisi["livello_confidenza"] = "ALTO" 
        return state

    if dispositivi_richiesti:
        for id_richiesto in dispositivi_richiesti:
            if id_richiesto.upper() in ["NESSUNO", "NULL", "NONE"]:
                continue

            target_disp = None

            for disp in state["dispositivi_attivi"]:
                if isinstance(disp, str):
                    try:
                        disp_dict = json.loads(disp)
                        if isinstance(disp_dict, dict) and id_richiesto.upper() == disp_dict.get("id_dispositivo", "").upper():
                            target_disp = disp_dict
                            break
                    except json.JSONDecodeError:
                        if id_richiesto.upper() in disp.upper():
                            target_disp = {
                                "id_dispositivo": id_richiesto,
                                "is_mobile": "drone" in disp.lower() or "mobile: sì" in disp.lower()
                            }
                            break
                
                elif isinstance(disp, dict):
                    if id_richiesto.upper() == disp.get("id_dispositivo", "").upper():
                        target_disp = disp
                        break

            if target_disp:
                    id_pulito = target_disp["id_dispositivo"]
                    is_mobile = target_disp.get("is_mobile", False)
                    print(f"[DEBUG ROUTER] Trovato {id_pulito}. Mobile: {is_mobile}. Invio comando MQTT!")
                    
                    topic = f"smartcity/comandi/{id_pulito}"

                    comando_payload = {
                        "comando": "RICHIEDI_DATO_EMERGENZA", 
                        "motivo": analisi.get("motivazione_analisi", "Verifica supplementare richiesta dall'AI")
                    }
                    
                    if is_mobile and lat_target is not None and lon_target is not None:
                        comando_payload["azione_tattica"] = "SPOSTAMENTO_RICHIESTO"
                        comando_payload["target_gps"] = {
                            "latitudine": lat_target, 
                            "longitudine": lon_target
                        }
                        print(f"[MQTT] -> Aggiunto ordine di spostamento verso {lat_target}, {lon_target} per {id_pulito}")
                    
                    client_pub.publish(topic, json.dumps(comando_payload))
            else:
                print(f"[DEBUG ROUTER] ATTENZIONE: Sensore '{id_richiesto}' non trovato o offline.")
                analisi["livello_confidenza"] = "ALTO"
        
    return state

def nodo_comandante(evento):
    """
    Nodo 3: COMANDANTE
    Legge il report, valuta le risorse IoT disponibili e decide l'intervento tattico.
    Se non c'è reale pericolo, annulla l'emergenza per non sprecare risorse.
    """
    epicentro_id = evento.get("epicentro_id", "Sconosciuto")
    lat_esatta = evento.get("lat_epicentro")
    lon_esatta = evento.get("lon_epicentro")
    contesto_eventi = evento.get("contesto_eventi", [])
    analisi = evento.get("analisi_json", {})
    dispositivi_attivi = evento.get("dispositivi_attivi", [])
    
    for ev in contesto_eventi:
        if "analisi_telecamera_vlm" in ev and ev.get("posizione") and ev["posizione"].get("coordinate"):
            lat_esatta = ev["posizione"]["coordinate"].get("latitudine")
            lon_esatta = ev["posizione"]["coordinate"].get("longitudine")
            break
            
    if lat_esatta is None or lon_esatta is None:
        if contesto_eventi and "posizione" in contesto_eventi[0] and contesto_eventi[0]["posizione"].get("coordinate"):
            lat_esatta = contesto_eventi[0]["posizione"]["coordinate"].get("latitudine")
            lon_esatta = contesto_eventi[0]["posizione"]["coordinate"].get("longitudine")
            
    coordinate_str = f"Latitudine: {lat_esatta}, Longitudine: {lon_esatta}" if lat_esatta else "Non specificate"
    dispositivi_trigger = list(set([ev.get("id_dispositivo") for ev in contesto_eventi if "id_dispositivo" in ev]))

    print(f"\n[NODO 3: COMANDANTE] Valutazione Intervento Strategico per {epicentro_id}...")
    
    dispositivi_str = ordina_e_taglia_dispositivi_comandante(dispositivi_attivi, lat_esatta, lon_esatta)

    prompt_comandante = get_prompt_comandante(
        epicentro_id=epicentro_id,
        coordinate_str=f"Lat: {lat_esatta}, Lon: {lon_esatta}",
        dispositivi_trigger=dispositivi_trigger,
        motivazione_analisi=analisi.get('motivazione_analisi', ''),
        pericoli_rilevati=analisi.get('pericoli_rilevati', []),
        dispositivi_str=dispositivi_str,
        lat_esatta=lat_esatta,
        lon_esatta=lon_esatta
    )
    
    # Invocazione LLM e Pubblicazione Ordini MQTT
    try:
        risposta_llm = llm.invoke(prompt_comandante)
        decisione = json_parser.invoke(risposta_llm)
        
        print("\n==================================================")
        print("INCIDENT REPORT")
        print(f"Target          : {decisione.get('posizione_esatta', {}).get('nome_zona')} ({coordinate_str})")
        print(f"Descrizione     : {decisione.get('descrizione_situazione', '')}")
        print(f"Sensori Alert   : {', '.join(decisione.get('dispositivi_coinvolti', []))}")
        print(f"Unità Umane     : {', '.join(decisione.get('unita_intervento_umano', []))}")
        print(f"Supporto IoT    : {', '.join(decisione.get('dispositivi_tattici_attivati', []))}")
        print("==================================================\n")
        
        evento["ordine_comandante"] = decisione

        dispositivi_attivati = decisione.get("dispositivi_tattici_attivati", [])
        if isinstance(dispositivi_attivati, str):
            dispositivi_attivati = [dispositivi_attivati]

        if dispositivi_attivati:
            for disp_id in dispositivi_attivati:
                if disp_id.upper() in ["NESSUNO", "NULL", "NONE", ""]:
                    continue
                    
                id_pulito = disp_id.split(" ")[0].strip()
                
                is_mobile = False
                for d in dispositivi_attivi:
                    if isinstance(d, dict) and d.get("id_dispositivo", "").upper() == id_pulito.upper():
                        is_mobile = d.get("is_mobile", False)
                        break

                    elif isinstance(d, str):
                        try:
                            d_dict = json.loads(d)
                            if d_dict.get("id_dispositivo", "").upper() == id_pulito.upper():
                                is_mobile = d_dict.get("is_mobile", False)
                                break
                        except json.JSONDecodeError:
                            if id_pulito.upper() in d.upper():
                                is_mobile = "drone" in d.lower() or "mobile: sì" in d.lower()
                                break

                topic_cmd = f"smartcity/comandi/{id_pulito}"
                payload_cmd = {
                    "comando": "DISPIEGAMENTO_TATTICO",
                    "ordine_operativo": decisione.get("ordine_operativo", ""),
                    "zona_target": epicentro_id
                }
                
                if is_mobile and lat_esatta is not None and lon_esatta is not None:
                    payload_cmd["azione_tattica"] = "SPOSTAMENTO_RICHIESTO"
                    payload_cmd["target_gps"] = {
                        "latitudine": lat_esatta, 
                        "longitudine": lon_esatta
                    }
                    print(f"[MQTT] -> Aggiunto ordine di spostamento tattico verso {lat_esatta}, {lon_esatta} per {id_pulito}")
                
                client_pub.publish(topic_cmd, json.dumps(payload_cmd))
                print(f"[MQTT] Ordine operativo inviato al dispositivo: {id_pulito}")
        
        stato_attuale_zona = r.get(f"smartcity:stato_emergenza:{epicentro_id}")
        if stato_attuale_zona != "CRITICO":
            r.set(f"smartcity:stato_emergenza:{epicentro_id}", "CRITICO")
            print(f"[STATE MACHINE] Stato della zona {epicentro_id} bloccato su CRITICO. L'IA monitorerà il rientro dell'emergenza.")

        payload_mappa = {
            "epicentro_id": epicentro_id, 
            "lat": lat_esatta, 
            "lon": lon_esatta, 
            "stato": "CRITICO"
        }
        client_pub.publish(f"smartcity/mappa/{epicentro_id}", json.dumps(payload_mappa))
        
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

def check_errori_investigatore(state: SmartCityState) -> str:
    if state.get("errore_parsing"):
        return "correttore"
    return decide_prossimo_nodo(state)

# 4. ASSEMBLAGGIO DEL GRAFO
def crea_grafo_smart_city():
    """Costruisce e compila il workflow di LangGraph per l'Orchestratore."""
    workflow = StateGraph(SmartCityState)
    
    workflow.add_node("investigatore", nodo_investigatore)
    workflow.add_node("correttore", nodo_correttore)
    workflow.add_node("router", nodo_router)
    workflow.add_node("comandante", nodo_comandante)

    workflow.set_entry_point("investigatore")
    
    workflow.add_conditional_edges(
        "investigatore",
        check_errori_investigatore,
        {
            "correttore": "correttore",
            "router": "router",
            "comandante": "comandante",
            "fine": END
        }
    )

    workflow.add_conditional_edges(
        "correttore",
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

    return workflow.compile()


app_smart_city = crea_grafo_smart_city()


r = redis.Redis(
    host=REDIS_HOST, 
    port=REDIS_PORT, 
    db=REDIS_DB, 
    password=REDIS_PASSWORD, 
    decode_responses=True
)

NUMERO_WORKER_PARALLELI = 3  
executor = ThreadPoolExecutor(max_workers=NUMERO_WORKER_PARALLELI)

def esegui_grafo(stato_iniziale):
    """Funzione eseguita dal singolo worker nel suo thread separato"""
    epicentro_id = stato_iniziale.get('epicentro_id', 'Sconosciuto')
    print(f"\n[AI CORE] Inizio elaborazione evento per {epicentro_id}...")
    
    try:
        app_smart_city.invoke(stato_iniziale)
    except Exception as e:
        print(f"[ERRORE AI CORE] Crash durante l'esecuzione del grafo: {e}")
    finally:
        buffer_key = f"smartcity:buffer_eventi:{epicentro_id}"
        lock_key = f"lock_analisi:{epicentro_id}"
        
        eventi_in_buffer = r.lrange(buffer_key, 0, -1)
        
        if eventi_in_buffer:
            print(f"\n[AI CORE] Trovati {len(eventi_in_buffer)} nuovi eventi nel buffer per {epicentro_id}!")
            print(f"[AI CORE] Riavvio immediato dell'analisi per processare i nuovi dati critici.")
            
            r.delete(buffer_key)
            
    
            r.set(lock_key, "1", ex=30)

            ultimo_evento = eventi_in_buffer[-1]
            r.rpush("smartcity:coda_lavori", ultimo_evento)
        else:

            r.delete(lock_key)
            print(f"[AI CORE] Analisi completata. Lock rilasciato per {epicentro_id}.")

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



