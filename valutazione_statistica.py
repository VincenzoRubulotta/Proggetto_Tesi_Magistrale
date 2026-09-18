import json
import re
from collections import Counter
from langchain_ollama import OllamaLLM
from langchain_core.prompts import PromptTemplate
from prompts import TEMPLATE_INVESTIGATORE, get_prompt_comandante

# Inizializziamo il modello (temperatura a 0.4 per un buon bilanciamento tra creatività e coerenza)
llm = OllamaLLM(model="llama3.2", base_url="http://localhost:11434", format="json", temperature=0.4)
prompt_inv = PromptTemplate(template=TEMPLATE_INVESTIGATORE, input_variables=["coordinate_epicentro", "contesto_eventi", "dispositivi_attivi"])
chain_investigatore = prompt_inv | llm

NUM_ITERAZIONI = 10  # Aumenta a 20, 30 o 50 per test accademici

# ==========================================
# COSTRUZIONE DEL GOLDEN DATASET
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

scenari = [
    {
        "nome": "SCENARIO 1: Falso Allarme (Boato ma strada tranquilla)",
        "coord": "37.514077, 15.092305",
        "contesto": json.dumps([
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato", "trascrizione_audio": "Forte boato e rumori metallici."}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "The image depicts an urban street scene with two cars parked on the side of the road and a van driving down the street. A tall building stands prominently in the background, surrounded by trees that provide some shade to the area. There are no visible signs of accidents or hazards, but several pedestrians can be seen walking along the sidewalk near the buildings."}
        ]),
        "atteso_inv_stato": "NORMALE",
        "mock_inv_motivazione": "Il VLM mostra un cantiere e pedoni tranquilli. Nessun pericolo confermato.",
        "mock_inv_pericoli": [],
        "atteso_com_drone": "NESSUNO"
    },
    {
        "nome": "SCENARIO 2: Incidente Stradale",
        "coord": "37.514511, 15.092750",
        "contesto": json.dumps([
            {"id_dispositivo": "MIC_EST", "dato_rilevato": {"allarme": "boato_rilevato", "trascrizione_audio": "Forte boato e rumori metallici."}},
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "The image shows two cars involved in an accident on the side of a road. One car is green and appears to be damaged, while the other car is yellow and also seems to have sustained damage. Both cars are parked next to each other, with their front ends facing opposite directions."}
        ]),
        "atteso_inv_stato": "CRITICO",
        "mock_inv_motivazione": "Il VLM conferma uno scontro tra due auto con danni visibili.",
        "mock_inv_pericoli": ["incidente stradale", "auto danneggiate"],
        "atteso_com_drone": "DRONE_01"
    },
    {
        "nome": "SCENARIO 3: Incendio Grattacielo",
        "coord": "37.514511, 15.092750",
        "contesto": json.dumps([
            {"id_dispositivo": "CAM_NORD", "analisi_telecamera_vlm": "The image shows a tall white building with a fire burning on the top floor. Thick black smoke is billowing out of the windows and rising into the sky, indicating that the fire has spread to multiple floors within the structure."}
        ]),
        "atteso_inv_stato": "CRITICO",
        "mock_inv_motivazione": "Il VLM mostra chiaramente un incendio attivo ai piani alti di un edificio con denso fumo nero.",
        "mock_inv_pericoli": ["incendio strutturale", "fumo"],
        "atteso_com_drone": "DRONE_02"
    }
]

# ==========================================
# VARIABILI STATISTICHE GLOBALI
# ==========================================
totale_run = len(scenari) * NUM_ITERAZIONI
global_inv_successi = 0
global_inv_errori_json = 0
global_com_successi = 0
global_com_errori_json = 0
global_com_allucinazioni_fissi = 0

print(f"Avvio test statistico: {len(scenari)} scenari x {NUM_ITERAZIONI} iterazioni = {totale_run} chiamate totali per agente.\n")

for idx, scenario in enumerate(scenari):
    print(f"\n{'='*50}\nTESTING: {scenario['nome']}\n{'='*50}")
    
    stats_inv_stati = []
    stats_inv_errori = 0
    stats_com_droni = []
    stats_com_errori = 0
    stats_com_allucinazioni_fissi = 0
    
    for i in range(NUM_ITERAZIONI):
        print(f"Iter {i+1}/{NUM_ITERAZIONI}...", end=" ", flush=True)
        
        # ----------------------------------------------------
        # 1. VALUTAZIONE INVESTIGATORE
        # ----------------------------------------------------
        raw_inv = chain_investigatore.invoke({
            "coordinate_epicentro": scenario["coord"],
            "contesto_eventi": scenario["contesto"],
            "dispositivi_attivi": disp_attivi_inv
        })
        try:
            testo_pulito = raw_inv.replace("```json", "").replace("```", "").strip()
            if "{" in testo_pulito and "}" in testo_pulito:
                testo_pulito = testo_pulito[testo_pulito.find("{"):testo_pulito.rfind("}")+1]
            res_inv = json.loads(testo_pulito)
            stats_inv_stati.append(res_inv.get("stato_zona", "SCONOSCIUTO"))
        except Exception:
            stats_inv_errori += 1
            stats_inv_stati.append("ERRORE_JSON")

        # ----------------------------------------------------
        # 2. VALUTAZIONE COMANDANTE (Con Input Mockato Perfetto)
        # ----------------------------------------------------
        prompt_com = get_prompt_comandante(
            epicentro_id="epi_test",
            coordinate_str=scenario["coord"],
            dispositivi_trigger=["CAM_NORD"],
            motivazione_analisi=scenario["mock_inv_motivazione"],
            pericoli_rilevati=scenario["mock_inv_pericoli"],
            dispositivi_str=disp_attivi_com,
            lat_esatta=37.514, lon_esatta=15.092
        )
        
        raw_com = llm.invoke(prompt_com)
        try:
            testo_pulito_com = raw_com.replace("```json", "").replace("```", "").strip()
            if "{" in testo_pulito_com and "}" in testo_pulito_com:
                testo_pulito_com = testo_pulito_com[testo_pulito_com.find("{"):testo_pulito_com.rfind("}")+1]
            res_com = json.loads(testo_pulito_com)
            
            droni_selezionati = res_com.get("dispositivi_tattici_attivati", [])
            if not droni_selezionati or droni_selezionati == ["NESSUNO"]:
                stats_com_droni.append("NESSUNO")
            else:
                stats_com_droni.extend(droni_selezionati)
                
            sensori_fissi = ["CAM_NORD", "MIC_EST", "TEMP_01"]
            if any(f in str(droni_selezionati) for f in sensori_fissi):
                stats_com_allucinazioni_fissi += 1
                
        except Exception:
            stats_com_errori += 1
            stats_com_droni.append("ERRORE_JSON")
            
        print("Fatto.")

    # --- RISULTATI PER SCENARIO ---
    count_inv = Counter(stats_inv_stati)
    count_com = Counter(stats_com_droni)
    
    successi_inv_scenario = count_inv.get(scenario['atteso_inv_stato'], 0)
    successi_com_scenario = count_com.get(scenario['atteso_com_drone'], 0)
    
    # Aggiornamento Variabili Globali
    global_inv_successi += successi_inv_scenario
    global_inv_errori_json += stats_inv_errori
    global_com_successi += successi_com_scenario
    global_com_errori_json += stats_com_errori
    global_com_allucinazioni_fissi += stats_com_allucinazioni_fissi
    
    inv_acc = (successi_inv_scenario / NUM_ITERAZIONI) * 100
    com_acc = (successi_com_scenario / NUM_ITERAZIONI) * 100
    
    print(f"\n--- REPORT PARZIALE: {scenario['nome']} ---")
    print(f"INVESTIGATORE: Accuratezza {inv_acc}% | Errori JSON: {stats_inv_errori}")
    print(f"  Distribuzione: {dict(count_inv)}")
    print(f"COMANDANTE: Accuratezza {com_acc}% | Allucinazioni Fissi: {stats_com_allucinazioni_fissi} | Errori JSON: {stats_com_errori}")
    print(f"  Distribuzione: {dict(count_com)}")


# ==========================================
# REPORT GLOBALE FINALE
# ==========================================
print("\n" + "="*50)
print(" 📊 REPORT GLOBALE E METRICHE DI SISTEMA")
print("="*50)

# Calcolo Metriche Globali
acc_globale_inv = (global_inv_successi / totale_run) * 100
err_globale_inv = (global_inv_errori_json / totale_run) * 100

acc_globale_com = (global_com_successi / totale_run) * 100
err_globale_com = (global_com_errori_json / totale_run) * 100
alluc_fissi_com = (global_com_allucinazioni_fissi / totale_run) * 100

print(f"🔹 NODO INVESTIGATORE (Task: Comprensione del contesto e Stato Zona)")
print(f"  - Accuratezza Decisionale Globale : {acc_globale_inv:.2f}% ({global_inv_successi}/{totale_run})")
print(f"  - Tasso Fallimento Sintassi JSON  : {err_globale_inv:.2f}% ({global_inv_errori_json}/{totale_run})")

print(f"\n🔹 NODO COMANDANTE (Task: Routing Tattico e Gestione Droni)")
print(f"  - Accuratezza Tattica Globale     : {acc_globale_com:.2f}% ({global_com_successi}/{totale_run})")
print(f"  - Tasso Allucinazione Entità Fisse: {alluc_fissi_com:.2f}% ({global_com_allucinazioni_fissi}/{totale_run})")
print(f"  - Tasso Fallimento Sintassi JSON  : {err_globale_com:.2f}% ({global_com_errori_json}/{totale_run})")

print("\nValutazione statistica completata.")
print("="*50)