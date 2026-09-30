import os
import hashlib
from flask import Flask, request, jsonify, send_from_directory
import time

app = Flask(__name__)

STORAGE_DIR = "archivio_foto"
os.makedirs(STORAGE_DIR, exist_ok=True)

@app.route('/upload', methods=['POST'])
def upload_immagine():
    if 'file' not in request.files:
        return jsonify({"errore": "Nessun file inviato"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"errore": "Nome file vuoto"}), 400

    file_bytes = file.read()
    md5_upload = hashlib.md5(file_bytes).hexdigest()
    print(f"[STORAGE] MD5 file in upload: {md5_upload}")

    file.seek(0)

    nome_file = f"cam_{int(time.time())}.jpg"
    percorso_salvataggio = os.path.join(STORAGE_DIR, nome_file)
    
    file.save(percorso_salvataggio)

    url_pubblico = f"{request.host_url}download/{nome_file}"
    
    print(f"[STORAGE] Nuova foto ricevuta! URL generato: {url_pubblico}")
    return jsonify({"messaggio": "Upload completato", "immagine_url": url_pubblico}), 200

@app.route('/download/<nome_file>', methods=['GET'])
def scarica_immagine(nome_file):
    percorso_file = os.path.join(STORAGE_DIR, nome_file)
    
    if os.path.exists(percorso_file):
        with open(percorso_file, "rb") as f:
            md5_download = hashlib.md5(f.read()).hexdigest()
        print(f"[STORAGE] Richiesto download di {nome_file} - MD5: {md5_download}")
        
    return send_from_directory(STORAGE_DIR, nome_file)

if __name__ == '__main__':
    print(f"Avvio Micro-Object Storage sulla porta 5000...")
    print(f"Cartella di archiviazione: {os.path.abspath(STORAGE_DIR)}")
    app.run(host='0.0.0.0', port=5000)