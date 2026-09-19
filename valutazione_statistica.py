import os
import json
import time
import base64
from collections import Counter
from dotenv import load_dotenv
from langchain_ollama import OllamaLLM, ChatOllama
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate
from prompts import TEMPLATE_INVESTIGATORE, get_prompt_comandante

# ==========================================
# VARIABILI D'AMBIENTE
# ==========================================
# Carica le variabili dal file .env
load_dotenv()

# Controllo di sicurezza
if not os.getenv("GROQ_API_KEY"):
    print("ATTENZIONE: Variabile GROQ_API_KEY non trovata nel file .env!")
    print("I test sui modelli Cloud falliranno. Assicurati di averla inserita.")

# ==========================================
# SCUDERIA MODELLI (Temp 0.0 per test deterministici)
# ==========================================
modelli_da_testare = {
    "1. Llama-3.2-3B (LOCALE EDGE - Jetson)": OllamaLLM(
        model="llama3.2", base_url="http://localhost:11434", format="json", temperature=0.0
    ),
    "2. Llama-3.2-3B (CLOUD API - Competitor Diretto)": ChatGroq(
        model_name="llama-3.2-3b-preview", temperature=0.0, model_kwargs={"response_format": {"type": "json_object"}}
    ),
    "3. Llama-3.1-8B (CLOUD API - Taglia Superiore)": ChatGroq(
        model_name="llama-3.1-8b-instant", temperature=0.0, model_kwargs={"response_format": {"type": "json_object"}}
    )
}

# Il VLM (Moondream) rimane in esecuzione locale sulla Jetson
vlm = ChatOllama(model="moondream", base_url="http://localhost:11434", temperature=0.0)

NUM_ITERAZIONI = 10  # Aumenta a 20 o 30 per raccogliere i dati finali della tesi

# ==========================================
# DISPOSITIVI SIMULATI
# ==========================================
disp_attivi_inv = """
- ID: DRONE_02 (Tipo: drone, Mobile: SÌ, Distanza: 132m, Batteria: 85%, Specializzazioni: [spegnimento_incendi, pompa_acqua])
- ID: MIC_EST (Tipo: microfono, Mobile: NO, Distanza: 0m, Batteria: 100%, Specializzazioni: [sirene, esplosioni, rumori_anomali])
- ID: CAM_NORD (Tipo: telecamera, Mobile: NO, Distanza: 62m, Batteria: N/D, Specializzazioni: [])
- ID: TEMP_01 (Tipo: sensore_temperatura, Mobile: NO, Distanza: 48m, Batteria: 100%, Specializzazioni: [incendi, rilevamento_calore])
- ID: DRONE_01 (Tipo: drone, Mobile: SÌ, Distanza: 242m, Batteria: 85%, Specializzazioni: [ricerca_visiva, telecamera])
- ID: DRONE_03 (Tipo: drone, Mobile: SÌ, Distanza: 734m, Batteria: 85%, Specializzazioni: [spegnimento_incendi, schiuma_ritardante])
"""

disp_attivi_com = """
[
  {"ID": "MIC_EST", "TIPO": "microfono", "IS_MOBILE": false, "DISTANZA_METRI": 0, "BATTERIA_PERCENTUALE": 100, "SPECIALIZZAZIONI": ["sirene", "esplosioni", "rumori_anomali"]},
  {"ID": "TEMP_01", "TIPO": "sensore_temperatura", "IS_MOBILE": false, "DISTANZA_METRI": 48, "BATTERIA_PERCENTUALE": 100, "SPECIALIZZAZIONI": ["incendi", "rilevamento_calore"]},
  {"ID": "CAM_NORD", "TIPO": "telecamera", "IS_MOBILE": false, "DISTANZA_METRI": 62, "BATTERIA_PERCENTUALE": 100, "SPECIALIZZAZIONI": []},
  {"ID": "DRONE_02", "TIPO": "drone", "IS_MOBILE": true, "DISTANZA_METRI": 132, "BATTERIA_PERCENTUALE": 85, "SPECIALIZZAZIONI": ["spegnimento_incendi", "pompa_acqua"]},
  {"ID": "DRONE_01", "TIPO": "drone", "IS_MOBILE": true, "DISTANZA_METRI": 242, "BATTERIA_PERCENTUALE": 85, "SPECIALIZZAZIONI": ["ricerca_visiva", "telecamera"]},
  {"ID": "DRONE_03", "TIPO": "drone", "IS_MOBILE": true, "DISTANZA_METRI": 734, "BATTERIA_PERCENTUALE": 85, "SPECIALIZZAZIONI": ["spegnimento_incendi", "schiuma_ritardante"]}
]
"""

# ==========================================
# FUNZIONE HELPER PER IL VLM
# ==========================================
def ottieni_contesto_visivo_reale(image_path):
    print(f"  [VLM] Estrazione descrizione reale da {image_path}...")
    try:
        with open(image_path, "rb") as image_file:
            image_b64 = base64.b64encode(image_file.read()).decode("utf-8")
        messaggio = HumanMessage(
            content=[
                {"type": "text", "text": "You are a security analyst. Describe exactly what you see in this image. Are there any accidents, hazards, vehicles, or people?"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
            ]
        )
        risposta = vlm.invoke([messaggio])
        descrizione = risposta.content.strip()
        print(f"  [VLM] Risultato: {descrizione}")
        return descrizione
    except Exception as e:
        print(f"  [VLM ERRORE] Impossibile leggere immagine: {e}")
        return "Error reading image."

# ==========================================
# GOLDEN DATASET
# ==========================================
scenari = [
    {
        "nome": "SCENARIO 1: Solo Microfono (Richiesta Ispezione)",
        "coord": "37.514077, 15.092305",
        "contesto": json.dumps([{"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato", "trascrizione_audio": "Forte boato e rumori metallici."}}]),
        "atteso_inv_stato": "ANOMALIA", "atteso_inv_richiesta": "CAM_NORD", "testa_comandante": False
    },
    {
        "nome": "SCENARIO 2: Solo Sensore Termico (Richiesta Ispezione)",
        "coord": "37.514206, 15.092822",
        "contesto": json.dumps([{"id_dispositivo": "TEMP_01", "dato_rilevato": {"allarme": "TEMPERATURA_CRITICA", "temperatura": 85.5}}]),
        "atteso_inv_stato": "ANOMALIA", "atteso_inv_richiesta": "CAM_NORD", "testa_comandante": False
    },
    {
        "nome": "SCENARIO 3: Solo Telecamera (Situazione Normale)",
        "coord": "37.514511, 15.092750",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/NORMALE/strada_normale_1.jpeg",
        "contesto_base": [{"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}],
        "atteso_inv_stato": "NORMALE", "atteso_inv_richiesta": "NESSUNO", "testa_comandante": False
    },
    {
        "nome": "SCENARIO 4: Solo Telecamera (Incendio Diretto)",
        "coord": "37.514511, 15.092750",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/CRITICO/incendio_palazzo.jpeg",
        "contesto_base": [{"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}],
        "atteso_inv_stato": "CRITICO", "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": True, "mock_inv_motivazione": "Incendio confermato visivamente.", "mock_inv_pericoli": ["incendio strutturale"], "atteso_com_drone": "DRONE_02"
    },
    {
        "nome": "SCENARIO 5: Solo Telecamera (Incidente Diretto)",
        "coord": "37.514511, 15.092750",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/CRITICO/incidente_stradale.jpeg",
        "contesto_base": [{"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}],
        "atteso_inv_stato": "CRITICO", "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": True, "mock_inv_motivazione": "Scontro tra veicoli.", "mock_inv_pericoli": ["incidente stradale"], "atteso_com_drone": "DRONE_01"
    },
    {
        "nome": "SCENARIO 6: Falso Allarme (Mic Boato -> Cam Normale)",
        "coord": "37.514077, 15.092305",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/NORMALE/strada_normale_2.jpeg",
        "contesto_base": [
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato"}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}
        ],
        "atteso_inv_stato": "NORMALE", "atteso_inv_richiesta": "NESSUNO", "testa_comandante": False
    },
    {
        "nome": "SCENARIO 7: Escalation Reale (Temp -> Incendio)",
        "coord": "37.514206, 15.092822",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/CRITICO/incendio_palazzo.jpeg",
        "contesto_base": [
            {"id_dispositivo": "TEMP_01", "dato_rilevato": {"allarme": "TEMPERATURA_CRITICA", "temperatura": 90.0}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}
        ],
        "atteso_inv_stato": "CRITICO", "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": True, "mock_inv_motivazione": "Incendio confermato.", "mock_inv_pericoli": ["incendio strutturale"], "atteso_com_drone": "DRONE_02"
    },
    {
        "nome": "SCENARIO 8: Escalation Reale (Mic Boato -> Cam Incendio)",
        "coord": "37.514077, 15.092305",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/CRITICO/incendio_palazzo.jpeg",
        "contesto_base": [
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato", "trascrizione_audio": "Forte boato e rumori metallici."}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}
        ],
        "atteso_inv_stato": "CRITICO", "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": True, "mock_inv_motivazione": "Il boato è stato confermato dalla telecamera.", "mock_inv_pericoli": ["incendio", "esplosione"], "atteso_com_drone": "DRONE_02"
    },
    {
        "nome": "SCENARIO 9: Escalation Reale (Mic Boato -> Cam Incidente Stradale)",
        "coord": "37.514077, 15.092305",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/CRITICO/incidente_stradale.jpeg",
        "contesto_base": [
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato", "trascrizione_audio": "Forte boato e rumori metallici prolungati."}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}
        ],
        "atteso_inv_stato": "CRITICO", "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": True, "mock_inv_motivazione": "Grave incidente stradale confermato.", "mock_inv_pericoli": ["incidente stradale"], "atteso_com_drone": "DRONE_01"
    }
]

# ==========================================
# PRE-COMPUTAZIONE VLM (Eseguita sulla Jetson)
# ==========================================
print("\n" + "="*70 + "\n FASE 1: PRE-COMPUTAZIONE VLM (Moondream in Locale)\n" + "="*70)
for scenario in scenari:
    if "immagine_reale" in scenario:
        desc = ottieni_contesto_visivo_reale(scenario["immagine_reale"])
        scenario["contesto_iniettato"] = json.dumps(scenario["contesto_base"]).replace("{VLM_PLACEHOLDER}", desc)
    else:
        scenario["contesto_iniettato"] = scenario["contesto"]

# ==========================================
# ESECUZIONE BENCHMARK COMPARATIVO
# ==========================================
prompt_inv = PromptTemplate(template=TEMPLATE_INVESTIGATORE, input_variables=["coordinate_epicentro", "contesto_eventi", "dispositivi_attivi"])
totale_run_inv = len(scenari) * NUM_ITERAZIONI
totale_run_com = sum(1 for s in scenari if s.get("testa_comandante")) * NUM_ITERAZIONI

statistiche_modelli = {}

for nome_modello, llm in modelli_da_testare.items():
    print(f"\n\n{'#'*80}\n AVVIO TEST: {nome_modello}\n{'#'*80}")
    
    chain_investigatore = prompt_inv | llm
    
    stats_modello = {
        "inv_successi_stato": 0, "inv_successi_routing": 0, "inv_tempi": [],
        "com_successi": 0, "com_tempi": [], "errori_json": 0
    }
    
    for scenario in scenari:
        print(f"\n  -> {scenario['nome']} ", end="", flush=True)
        
        for i in range(NUM_ITERAZIONI):
            print(".", end="", flush=True)
            
            # Pausa per evitare Rate Limit sulle API gratuite
            if "CLOUD API" in nome_modello:
                time.sleep(1.5) 
            
            # --- INVESTIGATORE ---
            start_inv = time.time()
            try:
                raw_inv = chain_investigatore.invoke({
                    "coordinate_epicentro": scenario["coord"],
                    "contesto_eventi": scenario["contesto_iniettato"],
                    "dispositivi_attivi": disp_attivi_inv
                })
                # Estrazione testuale compatibile con Ollama (str) e Groq (AIMessage)
                testo_inv = raw_inv.content if hasattr(raw_inv, 'content') else raw_inv
                testo_pulito = testo_inv.replace("```json", "").replace("```", "").strip()
                if "{" in testo_pulito and "}" in testo_pulito:
                    testo_pulito = testo_pulito[testo_pulito.find("{"):testo_pulito.rfind("}")+1]
                res_inv = json.loads(testo_pulito)
                
                if res_inv.get("stato_zona") == scenario['atteso_inv_stato']:
                    stats_modello["inv_successi_stato"] += 1
                
                req = res_inv.get("id_dispositivi_richiesti", [])
                scelta_req = req[0] if req else "NESSUNO"
                if scelta_req == scenario['atteso_inv_richiesta']:
                    stats_modello["inv_successi_routing"] += 1
            except Exception:
                stats_modello["errori_json"] += 1
            stats_modello["inv_tempi"].append(time.time() - start_inv)

            # --- COMANDANTE ---
            if scenario.get("testa_comandante"):
                prompt_com = get_prompt_comandante(
                    epicentro_id="epi_test", coordinate_str=scenario["coord"], dispositivi_trigger=["TEST"],
                    motivazione_analisi=scenario["mock_inv_motivazione"], pericoli_rilevati=scenario["mock_inv_pericoli"],
                    dispositivi_str=disp_attivi_com, lat_esatta=37.514, lon_esatta=15.092
                )
                start_com = time.time()
                try:
                    raw_com = llm.invoke(prompt_com)
                    testo_com = raw_com.content if hasattr(raw_com, 'content') else raw_com
                    testo_pulito_com = testo_com.replace("```json", "").replace("```", "").strip()
                    if "{" in testo_pulito_com and "}" in testo_pulito_com:
                        testo_pulito_com = testo_pulito_com[testo_pulito_com.find("{"):testo_pulito_com.rfind("}")+1]
                    res_com = json.loads(testo_pulito_com)
                    
                    droni = res_com.get("dispositivi_tattici_attivati", [])
                    scelta_drone = droni[0] if droni and droni != ["NESSUNO"] else "NESSUNO"
                    if scelta_drone == scenario['atteso_com_drone']:
                        stats_modello["com_successi"] += 1
                except Exception:
                    stats_modello["errori_json"] += 1
                stats_modello["com_tempi"].append(time.time() - start_com)
                
    statistiche_modelli[nome_modello] = stats_modello

# ==========================================
# REPORT COMPARATIVO FINALE
# ==========================================
print("\n\n" + "="*80)
print(" 📊 REPORT COMPARATIVO: EDGE vs CLOUD | SMALL vs LARGE MODEL")
print("="*80)

for nome, stats in statistiche_modelli.items():
    avg_inv_time = sum(stats["inv_tempi"]) / len(stats["inv_tempi"]) if stats["inv_tempi"] else 0
    avg_com_time = sum(stats["com_tempi"]) / len(stats["com_tempi"]) if stats["com_tempi"] else 0
    
    print(f"\n🔹 {nome}")
    print(f"  - Accuratezza Investigatore (Stato):   {(stats['inv_successi_stato'] / totale_run_inv) * 100:.2f}%")
    print(f"  - Accuratezza Investigatore (Routing): {(stats['inv_successi_routing'] / totale_run_inv) * 100:.2f}%")
    print(f"  - Accuratezza Comandante (Tattica):    {(stats['com_successi'] / totale_run_com) * 100:.2f}%")
    print(f"  - Latenza Media (Inv + Com):           {avg_inv_time + avg_com_time:.2f} sec totali")
    print(f"  - Errori Sintassi JSON:                {stats['errori_json']}")
print("="*80)