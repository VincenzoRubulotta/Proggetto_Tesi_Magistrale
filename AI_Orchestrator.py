import os
import json
import time
import queue
import math
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

DISPOSITIVI ATTUALMENTE ONLINE (Con Distanza dall'evento, Mobilità, Batteria e Specializzazioni):
{dispositivi_attivi}

IL TUO OBIETTIVO LOGICO:
Valuta gli eventi seguendo queste REGOLE ASSOLUTE:

IL TUO OBIETTIVO LOGICO:
Valuta gli eventi seguendo queste REGOLE ASSOLUTE:

1. TRADUZIONE: Traduci le descrizioni visive (VLM) dall'inglese all'italiano.
2. ADERENZA AI DATI: Usa SOLO i dati forniti. Non inventare immagini, pericoli o dispositivi inesistenti.
3. EMERGENZA CONFERMATA (ALTO): Se i dati o le immagini confermano in modo inequivocabile un'emergenza in corso (qualsiasi essa sia: strutturale, sanitaria, ambientale, criminale, ecc.), imposta lo stato su CRITICO, confidenza su ALTO e chiedi dispositivo NESSUNO.
4. INCERTEZZA E INDAGINE (MEDIO/BASSO): Se c'è un allarme da un sensore ma MANCA una conferma incrociata o visiva definitiva, lo stato è ANOMALIA e la confidenza è MEDIO. In questo caso, DEVI richiedere l'intervento di uno o più dispositivi dalla lista per un controllo supplementare. Scegli valutando:
   - COERENZA DELLE SPECIALIZZAZIONI: seleziona dispositivi le cui capacità siano logicamente utili per indagare il tipo specifico di anomalia rilevata.
   - DISTANZA: a parità di utilità, preferisci SEMPRE i dispositivi più vicini all'evento.
   - MOBILITÀ E BATTERIA: se scegli un dispositivo mobile ("IS_MOBILE": true) per l'ispezione, la sua batteria deve essere > 20.
5. PREVENZIONE LOOP: Non richiedere MAI l'intervento di un dispositivo il cui ID è già presente nel "contesto_eventi" come fonte dell'allarme.
6. RISOLUZIONE EMERGENZA (CESSATO ALLARME AUTONOMO): Se lo STATO OPERATIVO ATTUALE è "CRITICO", analizza L'ULTIMO evento in ordine cronologico. Puoi abbassare lo stato a "NORMALE" SOLO SE l'ultimo dato visivo (VLM) ricevuto descrive esplicitamente che la situazione è tornata tranquilla. Se i vecchi eventi mostrano l'emergenza ma l'evento più recente mostra la strada pulita, significa che il pericolo è rientrato e DEVI decretare lo stato NORMALE.

ESEMPIO 1 - COMPORTAMENTO IN CASO DI DUBBIO (Solo audio o temperatura, senza immagini):
{{
    "traduzione_e_fatti": "Il microfono rileva un forte boato.",
    "pericoli_rilevati": ["<INSERISCI_QUI_I_PERICOLI>"],
    "stato_zona": "ANOMALIA",
    "livello_confidenza": "MEDIO",
    "motivazione_analisi": "Allarme acustico grave. Richiedo la telecamera più vicina per ispezione visiva.",
    "id_dispositivi_richiesti": ["<INSERISCI_QUI_ID_REALE>"]
}}

ESEMPIO 2 - COMPORTAMENTO IN CASO DI CERTEZZA (Verifica visiva completata o emergenza palese):
{{
    "traduzione_e_fatti": "La telecamera mostra un cantiere. Non ci sono incidenti.",
    "pericoli_rilevati": [],
    "stato_zona": "NORMALE",
    "livello_confidenza": "ALTO",
    "motivazione_analisi": "L'immagine conferma che i rumori derivano da lavori. Nessun pericolo.",
    "id_dispositivi_richiesti": []
}}

Rispondi ESCLUSIVAMENTE in formato JSON usando questa struttura:
{{
    "traduzione_e_fatti": "La tua traduzione e i fatti.",
    "pericoli_rilevati": ["lista pericoli o vuoto"],
    "stato_zona": "NORMALE, ANOMALIA o CRITICO",
    "livello_confidenza": "ALTO, MEDIO o BASSO",
    "motivazione_analisi": "Il tuo ragionamento logico, specificando PERCHÉ hai scelto un determinato sensore in base alle sue specializzazioni.",
    "id_dispositivi_richiesti": ["Copia", "qui", "un array di ID esatti presi dalla lista", "oppure un array vuoto [] se ALTO"]
}}
"""
prompt = PromptTemplate(template=template_smart_city, input_variables=["nome_zona", "contesto_eventi", "dispositivi_attivi"])
analisi_chain = prompt | llm | JsonOutputParser()

client_pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client_pub.connect(MQTT_BROKER, MQTT_PORT, 60)
client_pub.loop_start()

def calcola_distanza(lat1, lon1, lat2, lon2):
    """Calcola la distanza in metri tra due coordinate GPS usando la formula di Haversine."""
    if None in (lat1, lon1, lat2, lon2):
        return float('inf') 
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ==========================================================
# ARCHITETTURA LANGGRAPH: LO STATO E I NODI
# ==========================================================

# 1. (State)
class SmartCityState(TypedDict):
    zona: str
    contesto_eventi: List[Dict[str, Any]]
    dispositivi_attivi: List[str]
    analisi_json: Optional[Dict[str, Any]]
    raw_text: Optional[str]        
    errore_parsing: Optional[str]

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
        lat_evento, lon_evento = None, None

        if state["contesto_eventi"] and "posizione" in state["contesto_eventi"][0]:
            coord = state["contesto_eventi"][0]["posizione"].get("coordinate")
            if coord:
                lat_evento = coord.get("latitudine")
                lon_evento = coord.get("longitudine")
        
        for ev in state["contesto_eventi"]:
            eventi_testo_pulito += f"- Dispositivo: {ev.get('nome_dispositivo', 'Sconosciuto')} ({ev.get('tipo_dispositivo', 'Sconosciuto')})\n"
            if "analisi_telecamera_vlm" in ev:
                eventi_testo_pulito += f"  Analisi Visiva (VLM): {ev['analisi_telecamera_vlm']}\n"
            if "dato_rilevato" in ev:
                eventi_testo_pulito += f"  Dato Sensore: {ev['dato_rilevato']}\n"
            eventi_testo_pulito += "\n"
        
        dispositivi_formattati = []
        for disp in state["dispositivi_attivi"]: 
            if isinstance(disp, str):
                try:
                    disp = json.loads(disp)
                except json.JSONDecodeError:
                    dispositivi_formattati.append(f"- {disp}")
                    continue
            if not isinstance(disp, dict):
                lat_disp = disp.get("posizione", {}).get("coordinate", {}).get("latitudine")
                lon_disp = disp.get("posizione", {}).get("coordinate", {}).get("longitudine")
                
                distanza = calcola_distanza(lat_evento, lon_evento, lat_disp, lon_disp)
                dist_str = f"{distanza:.0f}m" if distanza != float('inf') else "Sconosciuta"
                
                mob = "SÌ" if disp.get("is_mobile") else "NO"
                batt = f"{disp.get('batteria')}%" if disp.get("batteria") else "N/D"
                spec = ", ".join(disp.get("specializzazioni", []))
                
                info = f"- ID: {disp.get('id_dispositivo', 'Sconosciuto')} (Tipo: {disp.get('tipo_dispositivo', '')}, Mobile: {mob}, Distanza: {dist_str}, Batteria: {batt}, Specializzazioni: [{spec}])"
                dispositivi_formattati.append(info)

            lat_disp = disp.get("posizione", {}).get("coordinate", {}).get("latitudine")
            lon_disp = disp.get("posizione", {}).get("coordinate", {}).get("longitudine")
            
            distanza = calcola_distanza(lat_evento, lon_evento, lat_disp, lon_disp)
            dist_str = f"{distanza:.0f}m" if distanza != float('inf') else "Sconosciuta"
            
            mob = "SÌ" if disp.get("is_mobile") else "NO"
            batt = f"{disp.get('batteria')}%" if disp.get("batteria") else "N/D"
            spec = ", ".join(disp.get("specializzazioni", []))
            
            info = f"- ID: {disp['id_dispositivo']} (Tipo: {disp['tipo_dispositivo']}, Mobile: {mob}, Distanza dall'evento: {dist_str}, Batteria: {batt}, Specializzazioni: [{spec}])"
            dispositivi_formattati.append(info)

        print(f"\n[DEBUG INVESTIGATORE] Dispositivi attivi passati all'LLM: {state['dispositivi_attivi']}")

        stato_globale = gestore_registro.r.get(f"smartcity:stato_emergenza:{state['zona']}") or "NORMALE"
        print(f"[DEBUG INVESTIGATORE] Lo stato globale attuale della zona è: {stato_globale}")

        risposta_grezza = (prompt | llm).invoke({
            "nome_zona": state["zona"],
            "stato_globale": stato_globale,
            "contesto_eventi": json.dumps(state["contesto_eventi"], ensure_ascii=False),
            "dispositivi_attivi": "\n".join(dispositivi_formattati) if dispositivi_formattati else "Nessun dispositivo."
        })
        
        try:
            testo_pulito = risposta_grezza.replace("```json", "").replace("```", "").strip()
            if "{" in testo_pulito and "}" in testo_pulito:
                testo_pulito = testo_pulito[testo_pulito.find("{"):testo_pulito.rfind("}")+1]
                
            risultato = json.loads(testo_pulito)

            if risultato.get("stato_zona") == "NORMALE" and stato_globale == "CRITICO":
                gestore_registro.r.set(f"smartcity:stato_emergenza:{state['zona']}", "NORMALE")
                print(f"\n[STATE MACHINE] L'IA ha decretato il CESSATO ALLARME! La zona {state['zona']} è di nuovo sicura.")

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
    print(f"\n[NODO CORRETTORE] Tento di riparare la formattazione per la zona: {state['zona']}")
    
    template_correzione = """Hai generato un JSON non valido. 
Errore riscontrato dal parser: {errore}

Testo originale difettoso:
{testo_raw}

Correggi l'errore di sintassi e restituisci ESCLUSIVAMENTE il JSON valido, senza testo o markdown.
"""
    prompt_corr = PromptTemplate(template=template_correzione, input_variables=["errore", "testo_raw"])
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
    zona = state["zona"]
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
    zona = evento.get("zona", "Sconosciuta")
    contesto_eventi = evento.get("contesto_eventi", [])
    analisi = evento.get("analisi_json", {})
    dispositivi_attivi = evento.get("dispositivi_attivi", [])
    
    lat_esatta, lon_esatta = None, None

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

    print(f"\n[NODO 3: COMANDANTE] Valutazione Intervento Strategico per {zona}...")
    
    dispositivi_formattati = []
    for disp in dispositivi_attivi:
        if isinstance(disp, str):
            try:
                disp = json.loads(disp)
            except json.JSONDecodeError:
                dispositivi_formattati.append(f"- {disp}")
                continue
                
        if isinstance(disp, dict):
            lat_disp = disp.get("posizione", {}).get("coordinate", {}).get("latitudine")
            lon_disp = disp.get("posizione", {}).get("coordinate", {}).get("longitudine")
            
            distanza = calcola_distanza(lat_esatta, lon_esatta, lat_disp, lon_disp)
            distanza_int = int(distanza) if distanza != float('inf') else 9999
            
            is_mobile = "drone" in disp.get('tipo_dispositivo', '').lower() or disp.get("is_mobile") == True
            batteria = int(disp.get('batteria', 100)) # Assicuriamo sia un intero
            spec = disp.get("specializzazioni", [])
            
            info_dict = {
                "ID": disp.get('id_dispositivo', 'SCONOSCIUTO'),
                "TIPO": disp.get('tipo_dispositivo', 'sconosciuto'),
                "IS_MOBILE": is_mobile,
                "DISTANZA_METRI": distanza_int,
                "BATTERIA_PERCENTUALE": batteria,
                "SPECIALIZZAZIONI": spec
            }
            dispositivi_formattati.append(info_dict)

    dispositivi_formattati = sorted(dispositivi_formattati, key=lambda x: x['DISTANZA_METRI'])

    dispositivi_top_4 = dispositivi_formattati[:4]
    dispositivi_str = json.dumps(dispositivi_top_4, indent=2)

    prompt_comandante = f"""Sei il Comandante Operativo delle Forze di Sicurezza e Soccorso della Smart City.
Stai valutando una potenziale emergenza.

DATI DELL'EVENTO:
- Zona: {zona}
- Coordinate GPS: {coordinate_str}
- Dispositivi che hanno lanciato l'alert: {dispositivi_trigger}

REPORT DELL'INVESTIGATORE AI:
- Motivazione e Contesto Visivo: {analisi.get('motivazione_analisi', 'Nessuna descrizione')}
- Pericoli Rilevati: {analisi.get('pericoli_rilevati', [])}

ARRAY DEI DISPOSITIVI TATTICI ONLINE (Formato JSON):
{dispositivi_str}

IL TUO OBIETTIVO STRATEGICO E TATTICO:
1. VALUTAZIONE: Redigi una breve descrizione della situazione.
2. FORZE UMANE: Scegli chi dispiegare tra ["POLIZIA", "AMBULANZA", "VIGILI_DEL_FUOCO", "PROTEZIONE_CIVILE"] o "NESSUNO".
3. SUPPORTO CYBER-FISICO (IoT): I dispositivi con "IS_MOBILE": false sono INAMOVIBILI. Non puoi calcolare la loro distanza né 'inviarli'. Il tuo compito è valutare SOLO se inviare dispositivi mobili (droni) in supporto, rispettando queste regole:
   - REGOLA 1 (Coerenza Operativa): Scegli i dispositivi le cui "SPECIALIZZAZIONI" mitigano o analizzano direttamente i "Pericoli Rilevati" (intervento fisico, medico, analitico).
   - REGOLA 2 (Ottimizzazione Ridondanze): Evita gli sprechi. Se un sensore fisso presente in zona copre già una specifica necessità (es. ispezione visiva o acustica), non dispiegare unità mobili che offrono solo quella stessa capacità.
   - REGOLA 3 (Logistica delle Distanze): Tra i dispositivi con specializzazioni adatte, seleziona SEMPRE quello con il valore "DISTANZA_METRI" PIÙ BASSO (fai il calcolo matematico per confrontarli).
   - REGOLA 4 (Sicurezza Energetica): Dispiega dispositivi con "IS_MOBILE": true SOLO SE il loro valore "BATTERIA_PERCENTUALE" è strettamente > 20.

Rispondi ESCLUSIVAMENTE in formato JSON con questa esatta struttura ordinata:
{{
    "descrizione_situazione": "Descrizione dell'emergenza.",
    "dispositivi_coinvolti": ["Elenco ID dei dispositivi che hanno rilevato l'anomalia"],
    "posizione_esatta": {{
        "nome_zona": "{zona}",
        "latitudine": {lat_esatta if lat_esatta else "null"},
        "longitudine": {lon_esatta if lon_esatta else "null"}
    }},
    "unita_intervento_umano": ["Elenco forze umane"],
    "motivazione_tattica_iot": "Spiega la scelta finale basata ESCLUSIVAMENTE sulle specializzazioni, confermando di aver scelto il primo dispositivo utile della lista.",
    "dispositivi_tattici_attivati": ["Elenco ID dispositivi IoT scelti. Scrivi NESSUNO se non servono"]
}}
"""
    
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
                    "zona_target": zona
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
        
        stato_attuale_zona = r.get(f"smartcity:stato_emergenza:{zona}")
        if stato_attuale_zona != "CRITICO":
            r.set(f"smartcity:stato_emergenza:{zona}", "CRITICO")
            print(f"[STATE MACHINE] Stato della zona {zona} bloccato su CRITICO. L'IA monitorerà il rientro dell'emergenza.")

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

app_smart_city = workflow.compile()


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
    zona = stato_iniziale.get('zona', 'Sconosciuta')
    print(f"\n[AI CORE] Inizio elaborazione evento per {zona}...")
    
    try:
        app_smart_city.invoke(stato_iniziale)
    except Exception as e:
        print(f"[ERRORE AI CORE] Crash durante l'esecuzione del grafo: {e}")
    finally:
        buffer_key = f"smartcity:buffer_eventi:{zona}"
        lock_key = f"lock_analisi:{zona}"
        
        eventi_in_buffer = r.lrange(buffer_key, 0, -1)
        
        if eventi_in_buffer:
            print(f"\n[AI CORE] Trovati {len(eventi_in_buffer)} nuovi eventi nel buffer per {zona}!")
            print(f"[AI CORE] Riavvio immediato dell'analisi per processare i nuovi dati critici.")
            
            r.delete(buffer_key)
            
    
            r.set(lock_key, "1", ex=30)

            ultimo_evento = eventi_in_buffer[-1]
            r.rpush("smartcity:coda_lavori", ultimo_evento)
        else:

            r.delete(lock_key)
            print(f"[AI CORE] Analisi completata. Lock rilasciato per {zona}.")

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



