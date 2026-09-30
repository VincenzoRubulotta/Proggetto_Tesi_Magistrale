import os
import math
import json
import base64
import requests
import hashlib
from datetime import datetime, timezone
from langchain_core.messages import HumanMessage

def genera_file_cap(decisione_json, epicentro_id, cartella_destinazione="/app/alerts"):
    """Genera un file XML in standard CAP 1.2 dinamico basato sull'output del Comandante."""
    
    os.makedirs(cartella_destinazione, exist_ok=True)
    timestamp_attuale = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    
    cap_info = decisione_json.get("cap_info", {})
    category = cap_info.get("category", "Safety")
    urgency = cap_info.get("urgency", "Immediate")
    severity = cap_info.get("severity", "Severe")
    certainty = cap_info.get("certainty", "Observed")
    
    descrizione = decisione_json.get("descrizione_situazione", "Dettagli non disponibili.")
    lat = decisione_json.get("posizione_esatta", {}).get("latitudine", 0.0)
    lon = decisione_json.get("posizione_esatta", {}).get("longitudine", 0.0)
    area_circle = f"{lat},{lon} 0.1"

    event_name = f"Allarme di tipo {category}"
    
    cap_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">
  <identifier>{epicentro_id}</identifier>
  <sender>SmartCity_DigitalTwin_AI</sender>
  <sent>{timestamp_attuale}</sent>
  <status>Actual</status>
  <msgType>Alert</msgType>
  <scope>Public</scope>
  <info>
    <category>{category}</category>
    <event>{event_name}</event>
    <urgency>{urgency}</urgency>
    <severity>{severity}</severity>
    <certainty>{certainty}</certainty>
    <description>{descrizione}</description>
    <area>
      <areaDesc>Area Tattica Epicentro {epicentro_id}</areaDesc>
      <circle>{area_circle}</circle>
    </area>
  </info>
</alert>"""

    nome_file = f"{epicentro_id}.xml"
    percorso_file = os.path.join(cartella_destinazione, nome_file)
    
    with open(percorso_file, "w", encoding="utf-8") as f:
        f.write(cap_xml)
        
    print(f"[CAP GENERATOR] File standard CAP dinamico salvato: {percorso_file}")


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

def analizza_immagine_vlm(url_immagine, vlm_model):
    """Scarica l'immagine, la converte in Base64 e interroga il modello visivo."""
    try:
        risposta_http = requests.get(url_immagine, timeout=5)
        risposta_http.raise_for_status()
        
        contenuto_immagine = risposta_http.content

        md5_scaricato = hashlib.md5(contenuto_immagine).hexdigest()
        print(f"[VLM] Immagine scaricata da {url_immagine}")
        print(f"[VLM] MD5 file scaricato: {md5_scaricato}")

        image_b64 = base64.b64encode(risposta_http.content).decode("utf-8")
        
        prompt_strutturato = (
            "You are a security analyst. Let's think step by step.\n"
            "Step 1: Describe the background and the general environment you see.\n"
            "Step 2: List all the objects, vehicles, or people clearly visible.\n"
            "Step 3: Explicitly state if there are any accidents, hazards, or anomalies."
        )

        messaggio = HumanMessage(
            content=[
                {"type": "text", "text": prompt_strutturato},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
            ]
        )
        risposta_vlm = vlm_model.invoke([messaggio])
        testo_grezzo = risposta_vlm.content
        metadati = risposta_vlm.response_metadata
        print(f"URL Immagine: {url_immagine}")
        print(f"Testo esatto generato:\n'{testo_grezzo}'")
        print(f"Token in input (Letti): {metadati.get('prompt_eval_count', 'N/D')}")
        print(f"Token in output (Generati): {metadati.get('eval_count', 'N/D')}")
        print(f"Motivo dello stop (Done Reason): {metadati.get('done_reason', 'N/D')}")
        print(f"==================================\n")
        
        return risposta_vlm.content.strip()
    except Exception as e:
        print(f"[VLM] Errore durante l'analisi visiva: {e}")
        return None

def formatta_dispositivi_investigatore(dispositivi_attivi, lat_evento, lon_evento):
    """Prepara l'array testuale dei dispositivi per il prompt dell'Investigatore."""
    dispositivi_formattati = []
    for disp in dispositivi_attivi: 
        if isinstance(disp, str):
            try: disp = json.loads(disp)
            except json.JSONDecodeError: continue
        
        if isinstance(disp, dict):
            lat_disp = disp.get("posizione", {}).get("coordinate", {}).get("latitudine")
            lon_disp = disp.get("posizione", {}).get("coordinate", {}).get("longitudine")
            
            distanza = calcola_distanza(lat_evento, lon_evento, lat_disp, lon_disp)
            is_mobile = "drone" in disp.get('tipo_dispositivo', '').lower() or disp.get("is_mobile") == True
            
            if not is_mobile and distanza > 100:
                continue
                
            dist_str = f"{distanza:.0f}m" if distanza != float('inf') else "Sconosciuta"
            mob = "SÌ" if is_mobile else "NO"
            batt = f"{disp.get('batteria')}%" if disp.get("batteria") else "N/D"
            spec = ", ".join(disp.get("specializzazioni", []))
            
            info = f"- ID: {disp.get('id_dispositivo', 'Sconosciuto')} (Tipo: {disp.get('tipo_dispositivo', '')}, Mobile: {mob}, Distanza: {dist_str}, Batteria: {batt}, Specializzazioni: [{spec}])"
            dispositivi_formattati.append(info)
            
    return dispositivi_formattati

def ordina_e_taglia_dispositivi_comandante(dispositivi_attivi, lat_esatta, lon_esatta, max_items=None):
    dispositivi_formattati = []
    for disp in dispositivi_attivi:
        if isinstance(disp, str):
            try: disp = json.loads(disp)
            except json.JSONDecodeError: continue
                
        if isinstance(disp, dict):
            lat_disp = disp.get("posizione", {}).get("coordinate", {}).get("latitudine")
            lon_disp = disp.get("posizione", {}).get("coordinate", {}).get("longitudine")
            
            distanza = calcola_distanza(lat_esatta, lon_esatta, lat_disp, lon_disp)
            distanza_int = int(distanza) if distanza != float('inf') else 9999
            
            is_mobile = "drone" in disp.get('tipo_dispositivo', '').lower() or disp.get("is_mobile") == True
            
            if not is_mobile and distanza > 100:
                continue
                
            info_dict = {
                "ID": disp.get('id_dispositivo', 'SCONOSCIUTO'),
                "TIPO": disp.get('tipo_dispositivo', 'sconosciuto'),
                "IS_MOBILE": is_mobile,
                "DISTANZA_METRI": distanza_int,
                "BATTERIA_PERCENTUALE": int(disp.get('batteria', 100)),
                "SPECIALIZZAZIONI": disp.get("specializzazioni", [])
            }
            dispositivi_formattati.append(info_dict)
            
    dispositivi_ordinati = sorted(dispositivi_formattati, key=lambda x: x['DISTANZA_METRI'])
    if max_items is None:
        return json.dumps(dispositivi_ordinati, indent=2)
    return json.dumps(dispositivi_ordinati[:max_items], indent=2)