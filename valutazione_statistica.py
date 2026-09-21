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
# MODELLI (Edge & Cloud) - Temperature di default
# ==========================================
modelli_da_testare = {
    "1. GPT-OSS-20B (CLOUD API - Groq - FORZATO JSON)": ChatGroq(
        model_name="openai/gpt-oss-20b", 
        max_tokens=2048, 
        model_kwargs={"response_format": {"type": "json_object"}}
    ),
    "2. Qwen-2.5-3B (LOCALE EDGE - FORZATO JSON)": OllamaLLM(
        model="qwen2.5:3b", 
        base_url="http://localhost:11434", 
        format="json"
    ),
    "3. Llama-3.2-3B (LOCALE EDGE - FORZATO JSON)": OllamaLLM(
        model="llama3.2", 
        base_url="http://localhost:11434", 
        format="json"
    ),
    "4. Llama-3.2-3B (LOCALE EDGE - TESTO LIBERO)": OllamaLLM(
        model="llama3.2", 
        base_url="http://localhost:11434"
        # Parametro format="json" rimosso intenzionalmente
    )
}

vlm = ChatOllama(model="moondream", base_url="http://localhost:11434")
NUM_ITERAZIONI = 10 

# ==========================================
# DATABASE DISPOSITIVI DINAMICO 
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
# FUNZIONI HELPER
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

def estrai_tokens(raw_response, fallback_text):
    """Estrae i token generati in modo agnostico rispetto al provider (Groq/OpenAI/Ollama)."""
    if hasattr(raw_response, 'response_metadata'):
        meta = raw_response.response_metadata
        if 'eval_count' in meta: return meta['eval_count']  # Ollama
        if 'token_usage' in meta and 'completion_tokens' in meta['token_usage']:
            return meta['token_usage']['completion_tokens'] # Groq / OpenAI
    # Fallback matematico se i metadati non sono disponibili (stima: ~4 caratteri per token in JSON)
    return len(fallback_text) // 4

def calcola_percentile(dati, percentile):
    if not dati: return 0.0
    s_dati = sorted(dati)
    idx = int((percentile / 100) * len(s_dati))
    return s_dati[min(idx, len(s_dati)-1)]

# ==========================================
# DATASET COMPLETO
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
        "inv_successi_stato": 0, "inv_successi_routing": 0, 
        "inv_tempi_llm": [], "inv_tempi_totali": [], "inv_tps": [],
        "com_successi": 0, "com_tempi": [], "com_tps": [],
        "inv_errori_sintassi": 0, "com_errori_sintassi": 0, 
        "inv_allucinazioni_id": 0, "com_allucinazioni_id": 0,
        "dettaglio_scenari": {s["nome"]: {"inv_successi": 0, "com_successi": 0, "com_run": 0} for s in scenari}
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
                latenza_inv_llm = time.time() - start_inv
                testo_inv = raw_inv.content if hasattr(raw_inv, 'content') else raw_inv
                testo_pulito = testo_inv.replace("```json", "").replace("```", "").strip()
                if "{" in testo_pulito and "}" in testo_pulito:
                    testo_pulito = testo_pulito[testo_pulito.find("{"):testo_pulito.rfind("}")+1]
                res_inv = json.loads(testo_pulito)
                
                stato_ok = res_inv.get("stato_zona") == scenario['atteso_inv_stato']
                if stato_ok: stats_modello["inv_successi_stato"] += 1
                
                req = res_inv.get("id_dispositivi_richiesti", [])
                scelta_req = req[0] if req else "NESSUNO"
                
                routing_ok = False
                if scelta_req not in ID_VALIDI and scelta_req != "NESSUNO":
                    stats_modello["inv_allucinazioni_id"] += 1
                elif scelta_req in scenario['attesi_inv_richiesta']:
                    stats_modello["inv_successi_routing"] += 1
                    routing_ok = True
                
                if stato_ok and routing_ok:
                    stats_modello["dettaglio_scenari"][scenario["nome"]]["inv_successi"] += 1

                # Throughput e Latenze
                tok_inv = estrai_tokens(raw_inv, testo_inv)
                if latenza_inv_llm > 0: stats_modello["inv_tps"].append(tok_inv / latenza_inv_llm)
                stats_modello["inv_tempi_llm"].append(latenza_inv_llm)
                stats_modello["inv_tempi_totali"].append(latenza_inv_llm + scenario["vlm_latenza"])

            except json.JSONDecodeError:
                stats_modello["inv_errori_sintassi"] += 1
            except Exception as e:
                print(f"\n  [ERRORE API INVESTIGATORE] {e}")

            # --- COMANDANTE ---
            if scenario.get("testa_comandante"):
                stats_modello["dettaglio_scenari"][scenario["nome"]]["com_run"] += 1
                prompt_com = get_prompt_comandante(
                    epicentro_id="epi_test", coordinate_str=scenario["coord"], dispositivi_trigger=["TEST"],
                    motivazione_analisi=scenario["mock_inv_motivazione"], pericoli_rilevati=scenario["mock_inv_pericoli"],
                    dispositivi_str=disp_attivi_com_str, lat_esatta=lat_ev, lon_esatta=lon_ev
                )
                start_com = time.time()
                try:
                    raw_com = llm_model.invoke(prompt_com)
                    latenza_com = time.time() - start_com
                    testo_com = raw_com.content if hasattr(raw_com, 'content') else raw_com
                    testo_pulito_com = testo_com.replace("```json", "").replace("```", "").strip()
                    if "{" in testo_pulito_com and "}" in testo_pulito_com:
                        testo_pulito_com = testo_pulito_com[testo_pulito_com.find("{"):testo_pulito_com.rfind("}")+1]
                    res_com = json.loads(testo_pulito_com)
                    
                    droni = res_com.get("dispositivi_tattici_attivati", [])
                    scelta_drone = droni[0] if droni and droni != ["NESSUNO"] else "NESSUNO"
                    
                    if scelta_drone not in ID_VALIDI and scelta_drone != "NESSUNO":
                        stats_modello["com_allucinazioni_id"] += 1
                    elif scelta_drone in scenario['attesi_com_droni']:
                        stats_modello["com_successi"] += 1
                        stats_modello["dettaglio_scenari"][scenario["nome"]]["com_successi"] += 1
                    
                    tok_com = estrai_tokens(raw_com, testo_com)
                    if latenza_com > 0: stats_modello["com_tps"].append(tok_com / latenza_com)
                    stats_modello["com_tempi"].append(latenza_com)

                except json.JSONDecodeError:
                    stats_modello["com_errori_sintassi"] += 1
                except Exception as e:
                    print(f"\n  [ERRORE API COMANDANTE] {e}")
                
    statistiche_modelli[nome_modello] = stats_modello

# ==========================================
# REPORT COMPARATIVO FINALE E SALVATAGGIO TXT
# ==========================================
def genera_report(stats_dict, tot_inv, tot_com):
    report = []
    report.append("="*80)
    report.append(f" 📊 REPORT COMPARATIVO AVANZATO (Generato il {datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    report.append("="*80)
    
    for nome, stats in stats_dict.items():
        # Calcolo Medie
        avg_inv_llm = sum(stats["inv_tempi_llm"]) / len(stats["inv_tempi_llm"]) if stats["inv_tempi_llm"] else 0
        avg_inv_tot = sum(stats["inv_tempi_totali"]) / len(stats["inv_tempi_totali"]) if stats["inv_tempi_totali"] else 0
        avg_com = sum(stats["com_tempi"]) / len(stats["com_tempi"]) if stats["com_tempi"] else 0
        
        # Throughput
        tps_inv = sum(stats["inv_tps"]) / len(stats["inv_tps"]) if stats["inv_tps"] else 0
        tps_com = sum(stats["com_tps"]) / len(stats["com_tps"]) if stats["com_tps"] else 0
        
        # Percentili e WCET
        p95_inv = calcola_percentile(stats["inv_tempi_totali"], 95)
        p95_com = calcola_percentile(stats["com_tempi"], 95)
        wcet_inv = max(stats["inv_tempi_totali"]) if stats["inv_tempi_totali"] else 0
        wcet_com = max(stats["com_tempi"]) if stats["com_tempi"] else 0

        report.append(f"\n🔹 {nome}")
        report.append(f"  [METRICHE DI ACCURATEZZA]")
        report.append(f"  - Accuratezza Investigatore (Stato):   {(stats['inv_successi_stato'] / tot_inv) * 100:.2f}%")
        report.append(f"  - Accuratezza Investigatore (Routing): {(stats['inv_successi_routing'] / tot_inv) * 100:.2f}%")
        report.append(f"  - Accuratezza Comandante (Tattica):    {(stats['com_successi'] / tot_com) * 100:.2f}%")
        
        report.append(f"\n  [ANALISI PRESTAZIONALE DISACCOPPIATA]")
        report.append(f"  - Latenza Investigatore (Solo LLM):    {avg_inv_llm:.2f} s")
        report.append(f"  - Latenza Investigatore (LLM + VLM):   {avg_inv_tot:.2f} s")
        report.append(f"  - Throughput (Velocità Generazione):   Inv: {tps_inv:.1f} Tok/s | Com: {tps_com:.1f} Tok/s")
        report.append(f"  - Percentile Latenza (P95 End-to-End): Inv: {p95_inv:.2f} s | Com: {p95_com:.2f} s")
        report.append(f"  - Latenza Massima (WCET End-to-End):   Inv: {wcet_inv:.2f} s | Com: {wcet_com:.2f} s")
        
        report.append(f"\n  [TRACKING ERRORI E ALLUCINAZIONI]")
        report.append(f"  - Errori Sintassi JSON:                Inv: {stats['inv_errori_sintassi']} | Com: {stats['com_errori_sintassi']}")
        report.append(f"  - Allucinazioni ID Dispositivo:        Inv: {stats['inv_allucinazioni_id']} | Com: {stats['com_allucinazioni_id']}")
        
        report.append(f"\n  [DETTAGLIO CRITICITA' PER SCENARIO (Success rate < 100%)]")
        nessun_errore = True
        for scenario_nome, d in stats['dettaglio_scenari'].items():
            inv_rate = (d['inv_successi'] / NUM_ITERAZIONI) * 100
            if inv_rate < 100.0:
                report.append(f"    - {scenario_nome} [Investigatore]: {inv_rate:.0f}% successi")
                nessun_errore = False
            
            if d['com_run'] > 0:
                com_rate = (d['com_successi'] / d['com_run']) * 100
                if com_rate < 100.0:
                    report.append(f"    - {scenario_nome} [Comandante]:    {com_rate:.0f}% successi")
                    nessun_errore = False
        
        if nessun_errore:
            report.append(f"    - Il modello ha superato tutti gli scenari senza fallimenti specifici.")
            
        report.append("="*80)
    return "\n".join(report)

testo_report = genera_report(statistiche_modelli, totale_run_inv, totale_run_com)
print(testo_report)

# Salvataggio su file
file_name = f"benchmark_report_{int(time.time())}.txt"
with open(file_name, "w", encoding="utf-8") as f:
    f.write(testo_report)

print(f"\n✅ Il report avanzato è stato salvato correttamente nel file: {file_name}")