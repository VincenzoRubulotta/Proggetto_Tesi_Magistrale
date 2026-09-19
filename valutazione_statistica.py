import os
import json
import time
import base64
from datetime import datetime
from collections import Counter
from dotenv import load_dotenv
from langchain_ollama import OllamaLLM, ChatOllama
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage
from langchain_core.prompts import PromptTemplate
from prompts import TEMPLATE_INVESTIGATORE, get_prompt_comandante
from utils import formatta_dispositivi_investigatore, ordina_e_taglia_dispositivi_comandante

load_dotenv()

# ==========================================
# SCUDERIA MODELLI (Edge vs Cloud vs Competitors)
# ==========================================
modelli_da_testare = {
    "1. Phi-3-Mini-4K (CLOUD API - GitHub Models FREE)": ChatOpenAI(
        model="Phi-3-mini-4k-instruct", 
        api_key=os.getenv("GITHUB_TOKEN", "chiave_mancante"),
        base_url="https://models.inference.ai.azure.com",
        temperature=0.0,
        model_kwargs={"response_format": {"type": "json_object"}}
    ),
    "2. Llama-3.2-3B (CLOUD API - OpenRouter FREE)": ChatOpenAI(
        model="meta-llama/llama-3.2-3b-instruct",
        api_key=os.getenv("OPENROUTER_API_KEY", "chiave_mancante"),
        base_url="https://openrouter.ai/api/v1",
        temperature=0.0,
        model_kwargs={"response_format": {"type": "json_object"}}
    ),
    "3. GPT-OSS-20B (CLOUD API - Groq - Taglia Superiore)": ChatGroq(
        model_name="openai/gpt-oss-20b", temperature=0.0, model_kwargs={"response_format": {"type": "json_object"}}
    ),
    "4. Llama-3.2-3B (LOCALE EDGE - Jetson)": OllamaLLM(
        model="llama3.2", base_url="http://localhost:11434", format="json", temperature=0.0
    )
}

vlm = ChatOllama(model="moondream", base_url="http://localhost:11434")
NUM_ITERAZIONI = 10 

# ==========================================
# DATABASE DISPOSITIVI DINAMICO (Reale)
# ==========================================
dispositivi_db = [
    {"id_dispositivo": "MIC_EST", "tipo_dispositivo": "microfono", "is_mobile": False, "posizione": {"coordinate": {"latitudine": 37.514077, "longitudine": 15.092305}}, "batteria": 100, "specializzazioni": ["sirene", "esplosioni", "rumori_anomali"]},
    {"id_dispositivo": "TEMP_01", "tipo_dispositivo": "sensore_temperatura", "is_mobile": False, "posizione": {"coordinate": {"latitudine": 37.514206, "longitudine": 15.092822}}, "batteria": 100, "specializzazioni": ["incendi", "rilevamento_calore"]},
    {"id_dispositivo": "CAM_NORD", "tipo_dispositivo": "telecamera", "is_mobile": False, "posizione": {"coordinate": {"latitudine": 37.514511, "longitudine": 15.092750}}, "batteria": 100, "specializzazioni": []},
    {"id_dispositivo": "DRONE_01", "tipo_dispositivo": "drone", "is_mobile": True, "posizione": {"coordinate": {"latitudine": 37.516244, "longitudine": 15.092584}}, "batteria": 85, "specializzazioni": ["ricerca_visiva", "telecamera"]},
    {"id_dispositivo": "DRONE_02", "tipo_dispositivo": "drone", "is_mobile": True, "posizione": {"coordinate": {"latitudine": 37.5135, "longitudine": 15.0910}}, "batteria": 85, "specializzazioni": ["spegnimento_incendi", "pompa_acqua"]},
    {"id_dispositivo": "DRONE_03", "tipo_dispositivo": "drone", "is_mobile": True, "posizione": {"coordinate": {"latitudine": 37.5180, "longitudine": 15.0990}}, "batteria": 85, "specializzazioni": ["spegnimento_incendi", "schiuma_ritardante"]}
]
ID_VALIDI = [d["id_dispositivo"] for d in dispositivi_db]

# ==========================================
# FUNZIONE HELPER PER IL VLM (Con tracciamento Latenza)
# ==========================================
def ottieni_contesto_visivo_reale(image_path):
    print(f"  [VLM] Inferenza su {image_path}...")
    start_vlm = time.time()
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
        latenza = time.time() - start_vlm
        descrizione = risposta.content.strip()
        print(f"  [VLM] Completato in {latenza:.2f}s: {descrizione}")
        return descrizione, latenza
    except Exception as e:
        print(f"  [VLM ERRORE] {e}")
        return "Error reading image.", 0.0

# ==========================================
# GOLDEN DATASET COMPLETO (I 9 Scenari con Metriche Flessibili)
# ==========================================
scenari = [
    {
        "nome": "SCENARIO 1: Solo Microfono",
        "coord": "37.514077, 15.092305",
        "contesto": json.dumps([{"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato", "trascrizione_audio": "Forte boato e rumori metallici."}}]),
        "atteso_inv_stato": "ANOMALIA", 
        "attesi_inv_richiesta": ["CAM_NORD", "DRONE_01"],
        "testa_comandante": False
    },
    {
        "nome": "SCENARIO 2: Solo Sensore Termico",
        "coord": "37.514206, 15.092822",
        "contesto": json.dumps([{"id_dispositivo": "TEMP_01", "dato_rilevato": {"allarme": "TEMPERATURA_CRITICA", "temperatura": 85.5}}]),
        "atteso_inv_stato": "ANOMALIA", 
        "attesi_inv_richiesta": ["CAM_NORD", "DRONE_01"], 
        "testa_comandante": False
    },
    {
        "nome": "SCENARIO 3: Solo Telecamera (Normale)",
        "coord": "37.514511, 15.092750",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/NORMALE/strada_normale_1.jpeg",
        "contesto_base": [{"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}],
        "atteso_inv_stato": "NORMALE", 
        "attesi_inv_richiesta": ["NESSUNO"], 
        "testa_comandante": False
    },
    {
        "nome": "SCENARIO 4: Solo Telecamera (Incendio)",
        "coord": "37.514511, 15.092750",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/CRITICO/incendio_palazzo.jpeg",
        "contesto_base": [{"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}],
        "atteso_inv_stato": "CRITICO", 
        "attesi_inv_richiesta": ["NESSUNO"],
        "testa_comandante": True, 
        "mock_inv_motivazione": "Incendio confermato visivamente.", 
        "mock_inv_pericoli": ["incendio strutturale", "fumo"], 
        "attesi_com_droni": ["DRONE_02", "DRONE_03"] 
    },
    {
        "nome": "SCENARIO 5: Solo Telecamera (Incidente)",
        "coord": "37.514511, 15.092750",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/CRITICO/incidente_stradale.jpeg",
        "contesto_base": [{"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}],
        "atteso_inv_stato": "CRITICO", 
        "attesi_inv_richiesta": ["NESSUNO"],
        "testa_comandante": True, 
        "mock_inv_motivazione": "Scontro tra veicoli.", 
        "mock_inv_pericoli": ["incidente stradale", "veicoli danneggiati"], 
        "attesi_com_droni": ["DRONE_01"] 
    },
    {
        "nome": "SCENARIO 6: Falso Allarme (Mic Boato -> Cam Normale)",
        "coord": "37.514077, 15.092305",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/NORMALE/strada_normale_2.jpeg",
        "contesto_base": [
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato"}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}
        ],
        "atteso_inv_stato": "NORMALE", 
        "attesi_inv_richiesta": ["NESSUNO"], 
        "testa_comandante": False
    },
    {
        "nome": "SCENARIO 7: Escalation (Temp Alta -> Cam Incendio)",
        "coord": "37.514206, 15.092822",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/CRITICO/incendio_palazzo.jpeg",
        "contesto_base": [
            {"id_dispositivo": "TEMP_01", "dato_rilevato": {"allarme": "TEMPERATURA_CRITICA", "temperatura": 90.0}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}
        ],
        "atteso_inv_stato": "CRITICO", 
        "attesi_inv_richiesta": ["NESSUNO"],
        "testa_comandante": True, 
        "mock_inv_motivazione": "Allarme termico confermato visivamente: grave incendio in corso.", 
        "mock_inv_pericoli": ["incendio strutturale", "fumo"], 
        "attesi_com_droni": ["DRONE_02", "DRONE_03"]
    },
    {
        "nome": "SCENARIO 8: Escalation (Mic Boato -> Cam Incendio)",
        "coord": "37.514077, 15.092305",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/CRITICO/incendio_palazzo.jpeg",
        "contesto_base": [
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato", "trascrizione_audio": "Forte boato."}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}
        ],
        "atteso_inv_stato": "CRITICO", 
        "attesi_inv_richiesta": ["NESSUNO"],
        "testa_comandante": True, 
        "mock_inv_motivazione": "Il boato è stato confermato dalla telecamera: esplosione e incendio.", 
        "mock_inv_pericoli": ["incendio", "esplosione"], 
        "attesi_com_droni": ["DRONE_02", "DRONE_03"]
    },
    {
        "nome": "SCENARIO 9: Escalation (Mic Boato -> Cam Incidente)",
        "coord": "37.514077, 15.092305",
        "immagine_reale": "./Logica_di_Test/Data_Pool/Telecamere/CRITICO/incidente_stradale.jpeg",
        "contesto_base": [
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato", "trascrizione_audio": "Forte rumore metallico."}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "{VLM_PLACEHOLDER}"}
        ],
        "atteso_inv_stato": "CRITICO", 
        "attesi_inv_richiesta": ["NESSUNO"],
        "testa_comandante": True, 
        "mock_inv_motivazione": "Il rumore metallico è confermato: grave incidente stradale.", 
        "mock_inv_pericoli": ["incidente stradale", "traffico bloccato"], 
        "attesi_com_droni": ["DRONE_01"]
    }
]

# ==========================================
# PRE-COMPUTAZIONE VLM (Eseguita sulla Jetson)
# ==========================================
print("\n" + "="*70 + "\n FASE 1: PRE-COMPUTAZIONE VLM & DISTANZE SPAZIALI\n" + "="*70)

vlm_cache = {}

for scenario in scenari:
    scenario["vlm_latenza"] = 0.0
    if "immagine_reale" in scenario:
        img_path = scenario["immagine_reale"]
        if img_path not in vlm_cache:
            desc, latenza = ottieni_contesto_visivo_reale(img_path)
            vlm_cache[img_path] = {"desc": desc, "latenza": latenza}
        
        scenario["contesto_iniettato"] = json.dumps(scenario["contesto_base"]).replace("{VLM_PLACEHOLDER}", vlm_cache[img_path]["desc"])
        scenario["vlm_latenza"] = vlm_cache[img_path]["latenza"]
    else:
        scenario["contesto_iniettato"] = scenario["contesto"]

# ==========================================
# ESECUZIONE BENCHMARK COMPARATIVO
# ==========================================
prompt_inv = PromptTemplate(template=TEMPLATE_INVESTIGATORE, input_variables=["coordinate_epicentro", "contesto_eventi", "dispositivi_attivi"])
totale_run_inv = len(scenari) * NUM_ITERAZIONI
totale_run_com = sum(1 for s in scenari if s.get("testa_comandante")) * NUM_ITERAZIONI

statistiche_modelli = {}

for nome_modello, llm_model in modelli_da_testare.items():
    print(f"\n\n{'#'*80}\n AVVIO TEST: {nome_modello}\n{'#'*80}")
    
    chain_investigatore = prompt_inv | llm_model
    
    stats_modello = {
        "inv_successi_stato": 0, "inv_successi_routing": 0, "inv_tempi": [],
        "com_successi": 0, "com_tempi": [], 
        "errori_sintassi": 0, "allucinazioni_id": 0
    }
    
    for scenario in scenari:
        print(f"\n  -> {scenario['nome']} ", end="", flush=True)
        lat_ev, lon_ev = map(float, scenario["coord"].split(","))
        
        disp_attivi_inv_str = "\n".join(formatta_dispositivi_investigatore(dispositivi_db, lat_ev, lon_ev))
        disp_attivi_com_str = ordina_e_taglia_dispositivi_comandante(dispositivi_db, lat_ev, lon_ev)
        
        for i in range(NUM_ITERAZIONI):
            print(".", end="", flush=True)
            if "CLOUD API" in nome_modello: time.sleep(1.5) 
            
            # --- INVESTIGATORE ---
            start_inv = time.time()
            try:
                raw_inv = chain_investigatore.invoke({
                    "coordinate_epicentro": scenario["coord"],
                    "contesto_eventi": scenario["contesto_iniettato"],
                    "dispositivi_attivi": disp_attivi_inv_str
                })
                testo_inv = raw_inv.content if hasattr(raw_inv, 'content') else raw_inv
                testo_pulito = testo_inv.replace("```json", "").replace("```", "").strip()
                if "{" in testo_pulito and "}" in testo_pulito:
                    testo_pulito = testo_pulito[testo_pulito.find("{"):testo_pulito.rfind("}")+1]
                res_inv = json.loads(testo_pulito)
                
                if res_inv.get("stato_zona") == scenario['atteso_inv_stato']:
                    stats_modello["inv_successi_stato"] += 1
                
                req = res_inv.get("id_dispositivi_richiesti", [])
                scelta_req = req[0] if req else "NESSUNO"
                
                if scelta_req not in ID_VALIDI and scelta_req != "NESSUNO":
                    stats_modello["allucinazioni_id"] += 1
                elif scelta_req in scenario['attesi_inv_richiesta']:
                    stats_modello["inv_successi_routing"] += 1
                    
            except json.JSONDecodeError:
                stats_modello["errori_sintassi"] += 1
            except Exception as e:
                print(f"\n  [ERRORE API INVESTIGATORE] {e}")
            
            stats_modello["inv_tempi"].append((time.time() - start_inv) + scenario["vlm_latenza"])

            # --- COMANDANTE ---
            if scenario.get("testa_comandante"):
                prompt_com = get_prompt_comandante(
                    epicentro_id="epi_test", coordinate_str=scenario["coord"], dispositivi_trigger=["TEST"],
                    motivazione_analisi=scenario["mock_inv_motivazione"], pericoli_rilevati=scenario["mock_inv_pericoli"],
                    dispositivi_str=disp_attivi_com_str, lat_esatta=lat_ev, lon_esatta=lon_ev
                )
                start_com = time.time()
                try:
                    raw_com = llm_model.invoke(prompt_com)
                    testo_com = raw_com.content if hasattr(raw_com, 'content') else raw_com
                    testo_pulito_com = testo_com.replace("```json", "").replace("```", "").strip()
                    if "{" in testo_pulito_com and "}" in testo_pulito_com:
                        testo_pulito_com = testo_pulito_com[testo_pulito_com.find("{"):testo_pulito_com.rfind("}")+1]
                    res_com = json.loads(testo_pulito_com)
                    
                    droni = res_com.get("dispositivi_tattici_attivati", [])
                    scelta_drone = droni[0] if droni and droni != ["NESSUNO"] else "NESSUNO"
                    
                    if scelta_drone not in ID_VALIDI and scelta_drone != "NESSUNO":
                        stats_modello["allucinazioni_id"] += 1
                    elif scelta_drone in scenario['attesi_com_droni']:
                        stats_modello["com_successi"] += 1
                        
                except json.JSONDecodeError:
                    stats_modello["errori_sintassi"] += 1
                except Exception as e:
                    print(f"\n  [ERRORE API COMANDANTE] {e}")
                
                stats_modello["com_tempi"].append(time.time() - start_com)
                
    statistiche_modelli[nome_modello] = stats_modello

# ==========================================
# REPORT COMPARATIVO FINALE E SALVATAGGIO TXT
# ==========================================
def genera_report(stats_dict, tot_inv, tot_com):
    report = []
    report.append("="*80)
    report.append(f" 📊 REPORT COMPARATIVO END-TO-END (Generato il {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    report.append("="*80)
    
    for nome, stats in stats_dict.items():
        avg_inv_time = sum(stats["inv_tempi"]) / len(stats["inv_tempi"]) if stats["inv_tempi"] else 0
        avg_com_time = sum(stats["com_tempi"]) / len(stats["com_tempi"]) if stats["com_tempi"] else 0
        
        report.append(f"\n🔹 {nome}")
        report.append(f"  - Accuratezza Investigatore (Stato):   {(stats['inv_successi_stato'] / tot_inv) * 100:.2f}%")
        report.append(f"  - Accuratezza Investigatore (Routing): {(stats['inv_successi_routing'] / tot_inv) * 100:.2f}%")
        report.append(f"  - Accuratezza Comandante (Tattica):    {(stats['com_successi'] / tot_com) * 100:.2f}%")
        report.append(f"  - Latenza End-to-End Media:            {avg_inv_time + avg_com_time:.2f} sec (Incluso processing visivo VLM)")
        report.append(f"  - Errori Sintassi JSON (Fatal):        {stats['errori_sintassi']}")
        report.append(f"  - Allucinazioni ID Dispositivo:        {stats['allucinazioni_id']}")
    
    report.append("="*80)
    return "\n".join(report)

testo_report = genera_report(statistiche_modelli, totale_run_inv, totale_run_com)
print(testo_report)

# Salvataggio su file
file_name = f"benchmark_report_{int(time.time())}.txt"
with open(file_name, "w", encoding="utf-8") as f:
    f.write(testo_report)

print(f"\n✅ Il report è stato salvato correttamente nel file: {file_name}")