import os
import json
from flask import Flask, render_template
from flask_socketio import SocketIO
import paho.mqtt.client as mqtt

app = Flask(__name__)
app.config['SECRET_KEY'] = 'smartcity_secret'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = 1883

def on_connect(client, userdata, flags, reason_code, properties):
    print("Connesso al broker MQTT per la Dashboard!")
    client.subscribe("smartcity/heartbeat/#")
    client.subscribe("smartcity/logs/#")

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        topic = msg.topic
        
        if topic.startswith("smartcity/logs/"):
            socketio.emit('new_log', payload)
            
        elif topic.startswith("smartcity/heartbeat/"):
            socketio.emit('map_update', payload)
            
    except Exception as e:
        pass

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

if __name__ == '__main__':
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, 60)
    mqtt_client.loop_start()
    print("Avvio Dashboard su porta 8080...")
    socketio.run(app, host='0.0.0.0', port=8080)