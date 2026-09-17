
import math
import json
import base64
import requests
from langchain_core.messages import HumanMessage

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
        
        image_b64 = base64.b64encode(risposta_http.content).decode("utf-8")
        
        messaggio = HumanMessage(
            content=[
                {"type": "text", "text": "You are a security analyst. Describe exactly what you see in this image. Are there any accidents, hazards, vehicles, or people?"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
            ]
        )
        risposta_vlm = vlm_model.invoke([messaggio])
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