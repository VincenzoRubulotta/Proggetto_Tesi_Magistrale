import json
import time
from collections import Counter
from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate
from prompts import TEMPLATE_INVESTIGATORE, get_prompt_comandante

# Inizializzazione (temp 0.4)
llm = OllamaLLM(model="llama3.2", base_url="http://localhost:11434", format="json", temperature=0.4)
prompt_inv = PromptTemplate(template=TEMPLATE_INVESTIGATORE, input_variables=["coordinate_epicentro", "contesto_eventi", "dispositivi_attivi"])
chain_investigatore = prompt_inv | llm

NUM_ITERAZIONI = 10  # Aumenta a 30 per la tesi

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
# GOLDEN DATASET (I 9 SCENARI DINAMICI)
# ==========================================
scenari = [
    {
        "nome": "SCENARIO 1: Solo Microfono (Richiesta Ispezione)",
        "coord": "37.514077, 15.092305",
        "contesto": json.dumps([
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato", "trascrizione_audio": "Forte boato e rumori metallici."}}
        ]),
        "atteso_inv_stato": "ANOMALIA",
        "atteso_inv_richiesta": "CAM_NORD", 
        "testa_comandante": False
    },
    {
        "nome": "SCENARIO 2: Solo Sensore Termico (Richiesta Ispezione)",
        "coord": "37.514206, 15.092822",
        "contesto": json.dumps([
            {"id_dispositivo": "TEMP_01", "dato_rilevato": {"allarme": "TEMPERATURA_CRITICA", "temperatura": 85.5}}
        ]),
        "atteso_inv_stato": "ANOMALIA",
        "atteso_inv_richiesta": "CAM_NORD", 
        "testa_comandante": False
    },
    {
        "nome": "SCENARIO 3: Solo Telecamera (Situazione Normale)",
        "coord": "37.514511, 15.092750",
        "contesto": json.dumps([
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "The street is completely normal. Pedestrians are walking and cars are parked properly. No hazards."}
        ]),
        "atteso_inv_stato": "NORMALE",
        "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": False
    },
    {
        "nome": "SCENARIO 4: Solo Telecamera (Incendio Diretto)",
        "coord": "37.514511, 15.092750",
        "contesto": json.dumps([
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "A large fire is spreading in a building. Thick black smoke is coming out."}
        ]),
        "atteso_inv_stato": "CRITICO",
        "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": True,
        "mock_inv_motivazione": "La telecamera ha innescato direttamente un'emergenza per incendio strutturale.",
        "mock_inv_pericoli": ["incendio"],
        "atteso_com_drone": "DRONE_02"
    },
    {
        "nome": "SCENARIO 5: Solo Telecamera (Incidente Diretto)",
        "coord": "37.514511, 15.092750",
        "contesto": json.dumps([
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "Two cars collided at the intersection. Damaged vehicles."}
        ]),
        "atteso_inv_stato": "CRITICO",
        "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": True,
        "mock_inv_motivazione": "Scontro tra veicoli confermato visivamente dalla telecamera.",
        "mock_inv_pericoli": ["incidente stradale"],
        "atteso_com_drone": "DRONE_01"
    },
    {
        "nome": "SCENARIO 6: Falso Allarme (Mic Boato -> Cam Normale)",
        "coord": "37.514077, 15.092305",
        "contesto": json.dumps([
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato"}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "Street is normal, a large truck just dropped a metal container safely. No accidents."}
        ]),
        "atteso_inv_stato": "NORMALE",
        "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": False
    },
    {
        "nome": "SCENARIO 7: Escalation Reale (Temp Alta -> Cam Incendio)",
        "coord": "37.514206, 15.092822",
        "contesto": json.dumps([
            {"id_dispositivo": "TEMP_01", "dato_rilevato": {"allarme": "TEMPERATURA_CRITICA", "temperatura": 90.0}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "Fire and smoke visible from the nearby dumpster spreading to a car."}
        ]),
        "atteso_inv_stato": "CRITICO",
        "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": True,
        "mock_inv_motivazione": "Allarme termico confermato visivamente: incendio di un'auto e cassonetto in corso.",
        "mock_inv_pericoli": ["incendio", "fuoco auto"],
        "atteso_com_drone": "DRONE_02"
    },
    {
        "nome": "SCENARIO 8: Escalation Reale (Mic Boato -> Cam Incendio)",
        "coord": "37.514077, 15.092305",
        "contesto": json.dumps([
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato", "trascrizione_audio": "Forte boato e rumori metallici."}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "A large explosion has occurred at a street food stand. Fire is spreading rapidly and thick black smoke is visible."}
        ]),
        "atteso_inv_stato": "CRITICO",
        "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": True,
        "mock_inv_motivazione": "Il boato è stato confermato dalla telecamera: esplosione e incendio in corso.",
        "mock_inv_pericoli": ["incendio", "esplosione"],
        "atteso_com_drone": "DRONE_02"
    },
    {
        "nome": "SCENARIO 9: Escalation Reale (Mic Boato -> Cam Incidente Stradale)",
        "coord": "37.514077, 15.092305",
        "contesto": json.dumps([
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato", "trascrizione_audio": "Forte boato e rumori metallici prolungati."}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "Two vehicles have crashed violently into a lamppost. Debris is scattered across the road, and traffic is completely blocked."}
        ]),
        "atteso_inv_stato": "CRITICO",
        "atteso_inv_richiesta": "NESSUNO",
        "testa_comandante": True,
        "mock_inv_motivazione": "Il rumore metallico è stato confermato: grave incidente stradale con detriti sulla carreggiata.",
        "mock_inv_pericoli": ["incidente stradale", "detriti", "traffico bloccato"],
        "atteso_com_drone": "DRONE_01"
    }
]

# ==========================================
# VARIABILI GLOBALI E ESECUZIONE
# ==========================================
global_inv_successi_stato = 0
global_inv_successi_routing = 0
global_inv_tempi = []

global_com_successi = 0
global_com_tempi = []

totale_run_inv = len(scenari) * NUM_ITERAZIONI
totale_run_com = sum(1 for s in scenari if s["testa_comandante"]) * NUM_ITERAZIONI

print(f"Avvio Benchmark Avanzato: {len(scenari)} scenari x {NUM_ITERAZIONI} iterazioni.\n")

for scenario in scenari:
    print(f"\n{'='*60}\nTESTING: {scenario['nome']}\n{'='*60}")
    
    stats_inv_stati = []
    stats_inv_richieste = []
    stats_inv_tempi_scenario = []
    
    stats_com_droni = []
    stats_com_tempi_scenario = []
    
    for i in range(NUM_ITERAZIONI):
        print(f".", end="", flush=True)
        
        # --- TEST INVESTIGATORE ---
        start_time_inv = time.time()
        raw_inv = chain_investigatore.invoke({
            "coordinate_epicentro": scenario["coord"],
            "contesto_eventi": scenario["contesto"],
            "dispositivi_attivi": disp_attivi_inv
        })
        end_time_inv = time.time()
        stats_inv_tempi_scenario.append(end_time_inv - start_time_inv)
        
        try:
            testo_pulito = raw_inv.replace("```json", "").replace("```", "").strip()
            if "{" in testo_pulito and "}" in testo_pulito:
                testo_pulito = testo_pulito[testo_pulito.find("{"):testo_pulito.rfind("}")+1]
            res_inv = json.loads(testo_pulito)
            
            stats_inv_stati.append(res_inv.get("stato_zona", "ERRORE"))
            richieste = res_inv.get("id_dispositivi_richiesti", [])
            stats_inv_richieste.append(richieste[0] if richieste else "NESSUNO")
        except Exception:
            stats_inv_stati.append("ERRORE_JSON")
            stats_inv_richieste.append("ERRORE_JSON")

        # --- TEST COMANDANTE (Se applicabile) ---
        if scenario["testa_comandante"]:
            prompt_com = get_prompt_comandante(
                epicentro_id="epi_test",
                coordinate_str=scenario["coord"],
                dispositivi_trigger=["TRIGGER_TEST"],
                motivazione_analisi=scenario["mock_inv_motivazione"],
                pericoli_rilevati=scenario["mock_inv_pericoli"],
                dispositivi_str=disp_attivi_com,
                lat_esatta=37.514, lon_esatta=15.092
            )
            
            start_time_com = time.time()
            raw_com = llm.invoke(prompt_com)
            end_time_com = time.time()
            stats_com_tempi_scenario.append(end_time_com - start_time_com)
            
            try:
                testo_pulito_com = raw_com.replace("```json", "").replace("```", "").strip()
                if "{" in testo_pulito_com and "}" in testo_pulito_com:
                    testo_pulito_com = testo_pulito_com[testo_pulito_com.find("{"):testo_pulito_com.rfind("}")+1]
                res_com = json.loads(testo_pulito_com)
                
                droni = res_com.get("dispositivi_tattici_attivati", [])
                stats_com_droni.append(droni[0] if droni and droni != ["NESSUNO"] else "NESSUNO")
            except Exception:
                stats_com_droni.append("ERRORE_JSON")

    print(" Fatto!")
    
    # --- CALCOLI REPORT SCENARIO ---
    count_inv = Counter(stats_inv_stati)
    count_req = Counter(stats_inv_richieste)
    
    acc_inv_stato = (count_inv.get(scenario['atteso_inv_stato'], 0) / NUM_ITERAZIONI) * 100
    acc_inv_routing = (count_req.get(scenario['atteso_inv_richiesta'], 0) / NUM_ITERAZIONI) * 100
    avg_time_inv = sum(stats_inv_tempi_scenario) / len(stats_inv_tempi_scenario)
    
    global_inv_successi_stato += count_inv.get(scenario['atteso_inv_stato'], 0)
    global_inv_successi_routing += count_req.get(scenario['atteso_inv_richiesta'], 0)
    global_inv_tempi.extend(stats_inv_tempi_scenario)
    
    print(f"INVESTIGATORE:")
    print(f"  - Obiettivo Stato [{scenario['atteso_inv_stato']}]: {acc_inv_stato}%")
    print(f"  - Obiettivo Routing [{scenario['atteso_inv_richiesta']}]: {acc_inv_routing}%")
    print(f"  - Tempo Medio Risposta: {avg_time_inv:.2f} secondi")
    print(f"  - Dettaglio Stati: {dict(count_inv)}")
    print(f"  - Dettaglio Routing: {dict(count_req)}")
    
    if scenario["testa_comandante"]:
        count_com = Counter(stats_com_droni)
        acc_com = (count_com.get(scenario['atteso_com_drone'], 0) / NUM_ITERAZIONI) * 100
        avg_time_com = sum(stats_com_tempi_scenario) / len(stats_com_tempi_scenario)
        
        global_com_successi += count_com.get(scenario['atteso_com_drone'], 0)
        global_com_tempi.extend(stats_com_tempi_scenario)
        
        print(f"COMANDANTE:")
        print(f"  - Obiettivo Tattico [{scenario['atteso_com_drone']}]: {acc_com}%")
        print(f"  - Tempo Medio Risposta: {avg_time_com:.2f} secondi")
        print(f"  - Dettaglio Droni Scelti: {dict(count_com)}")


# ==========================================
# REPORT GLOBALE FINALE
# ==========================================
print("\n" + "="*60)
print(" 📊 METRICHE GLOBALI DEL DIGITAL TWIN")
print("="*60)

avg_global_inv_time = sum(global_inv_tempi) / len(global_inv_tempi) if global_inv_tempi else 0
avg_global_com_time = sum(global_com_tempi) / len(global_com_tempi) if global_com_tempi else 0

print(f"🔹 NODO INVESTIGATORE ({totale_run_inv} inferenze totali)")
print(f"  - Accuratezza Comprensione Stato: {(global_inv_successi_stato / totale_run_inv) * 100:.2f}%")
print(f"  - Accuratezza Routing (Scelta Sensore): {(global_inv_successi_routing / totale_run_inv) * 100:.2f}%")
print(f"  - Latenza Media: {avg_global_inv_time:.2f} secondi")

print(f"\n🔹 NODO COMANDANTE ({totale_run_com} inferenze totali)")
print(f"  - Accuratezza Scelta Tattica: {(global_com_successi / totale_run_com) * 100:.2f}%")
print(f"  - Latenza Media: {avg_global_com_time:.2f} secondi")
print("="*60)