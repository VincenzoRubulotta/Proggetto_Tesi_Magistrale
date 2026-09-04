FROM python:3.10-slim
WORKDIR /app
RUN pip install paho-mqtt requests python-dotenv
COPY device_node.py /app/
CMD ["python", "device_node.py"]