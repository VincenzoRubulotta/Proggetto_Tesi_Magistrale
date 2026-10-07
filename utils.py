import os
import math
import json
import base64
import requests
import hashlib
import time
import uuid
import xml.etree.ElementTree as ET

from datetime import timedelta
from zoneinfo import ZoneInfo
from datetime import datetime, timezone
from langchain_core.messages import HumanMessage

CAP_NS = "urn:oasis:names:tc:emergency:cap:1.2"
ET.register_namespace("", CAP_NS)


def _cap(tag):
    return f"{{{CAP_NS}}}{tag}"


CATEGORIE_CAP_IT = {
    "Geo", "Met", "Safety", "Security", "Rescue", "Fire",
    "Health", "Env", "Transport", "Infra", "CBRNE", "Other"
}

URGENZE_CAP_IT = {
    "Immediate", "Expected", "Future", "Past", "Unknown"
}

SEVERITA_CAP_IT = {
    "Extreme", "Severe", "Moderate", "Minor", "Unknown"
}

CERTEZZE_CAP_IT = {
    "Observed", "Likely", "Possible", "Unlikely", "Unknown"
}

RESPONSE_TYPE_CAP_IT = {
    "Shelter", "Evacuate", "Prepare", "Execute",
    "Avoid", "Monitor", "Assess", "AllClear", "None"
}


def genera_file_cap(decisione_json,epicentro_id,sender="SMARTCITY-DT-PROTOTYPE",sender_name="Digital Twin Cognitivo Smart City - Prototipo",geocode_value_name=None,geocode_value=None,cartella_destinazione="/app/alerts",):
    os.makedirs(cartella_destinazione, exist_ok=True)

    cap_info = decisione_json.get("cap_info", {})

    category = cap_info.get("category", "Safety")
    urgency = cap_info.get("urgency", "Unknown")
    severity = cap_info.get("severity", "Unknown")
    certainty = cap_info.get("certainty", "Unknown")
    response_type = cap_info.get("response_type", "Monitor")

    if category not in CATEGORIE_CAP_IT:
        category = "Other"

    if urgency not in URGENZE_CAP_IT:
        urgency = "Unknown"

    if severity not in SEVERITA_CAP_IT:
        severity = "Unknown"

    if certainty not in CERTEZZE_CAP_IT:
        certainty = "Unknown"

    if response_type not in RESPONSE_TYPE_CAP_IT:
        response_type = "Monitor"

    descrizione = decisione_json.get(
        "descrizione_situazione",
        "Dettagli non disponibili."
    )

    event = cap_info.get("event", f"Evento Smart City - {category}")
    headline = cap_info.get(
        "headline",
        f"Allerta Smart City - {category}"
    )[:160]

    instruction = cap_info.get(
        "instruction",
        "Monitorare l'evoluzione dell'evento."
    )

    posizione = decisione_json.get("posizione_esatta", {})
    lat = posizione.get("latitudine")
    lon = posizione.get("longitudine")

    identifier = str(uuid.uuid4())

    status = "Test"

    ora_italiana = datetime.now(ZoneInfo("Europe/Rome"))
    sent = ora_italiana.isoformat(timespec="seconds")

    expires = (ora_italiana + timedelta(hours=1)).isoformat(
        timespec="seconds"
    )

    root = ET.Element(_cap("alert"))

    ET.SubElement(root, _cap("identifier")).text = identifier
    ET.SubElement(root, _cap("sender")).text = sender
    ET.SubElement(root, _cap("sent")).text = sent
    ET.SubElement(root, _cap("status")).text = status
    ET.SubElement(root, _cap("msgType")).text = "Alert"
    ET.SubElement(root, _cap("source")).text = "SmartCity Digital Twin"
    ET.SubElement(root, _cap("scope")).text = "Public"
    ET.SubElement(root, _cap("code")).text = "CAP-IT:1.0"

    # CAP-IT richiede una nota circostanziata per i messaggi Test
    ET.SubElement(root, _cap("note")).text = (
        "Messaggio CAP-IT generato in ambiente sperimentale "
        "nell'ambito del prototipo Digital Twin Cognitivo."
    )

    info = ET.SubElement(root, _cap("info"))

    ET.SubElement(info, _cap("language")).text = "it-IT"
    ET.SubElement(info, _cap("category")).text = category
    ET.SubElement(info, _cap("event")).text = event
    ET.SubElement(info, _cap("responseType")).text = response_type
    ET.SubElement(info, _cap("urgency")).text = urgency
    ET.SubElement(info, _cap("severity")).text = severity
    ET.SubElement(info, _cap("certainty")).text = certainty

    ET.SubElement(info, _cap("effective")).text = sent
    ET.SubElement(info, _cap("expires")).text = expires

    ET.SubElement(info, _cap("senderName")).text = sender_name
    ET.SubElement(info, _cap("headline")).text = headline
    ET.SubElement(info, _cap("description")).text = descrizione

    if response_type in {
        "Shelter", "Evacuate", "Prepare", "Execute",
        "Avoid", "Monitor", "AllClear"
    }:
        ET.SubElement(info, _cap("instruction")).text = instruction

    if lat is not None and lon is not None:
        area = ET.SubElement(info, _cap("area"))

        ET.SubElement(
            area,
            _cap("areaDesc")
        ).text = f"Area tattica epicentro {epicentro_id}"

        ET.SubElement(
            area,
            _cap("circle")
        ).text = f"{lat},{lon} 0.1"

        if geocode_value_name and geocode_value:
            geocode = ET.SubElement(area, _cap("geocode"))
            ET.SubElement(
                geocode,
                _cap("valueName")
            ).text = geocode_value_name
            ET.SubElement(
                geocode,
                _cap("value")
            ).text = geocode_value

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")

    epoch = int(time.time())
    nome_file = f"{sender}_{identifier}_{epoch}.xml"
    percorso_file = os.path.join(
        cartella_destinazione,
        nome_file
    )

    tree.write(
        percorso_file,
        encoding="utf-8",
        xml_declaration=True
    )

    print(
        f"[CAP-IT GENERATOR] File CAP-IT sperimentale salvato: "
        f"{percorso_file}"
    )

    return percorso_file


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