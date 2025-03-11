import meshtastic
import time
import random
import threading
import json
import logging
import os

# Configuration Loading
CONFIG_FILE = "cluster_config.json"
DEFAULT_CONFIG = {
    "node_id": random.randint(1000, 9999),
    "heartbeat_interval": 10,
    "ack_timeout": 5,
    "rebroadcast_delay": 2,
    "message_retention": 20,
    "cluster_discovery_interval": 30,
    "sleep_interval": 60,
}

def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
            return {**DEFAULT_CONFIG, **config}  # Merge defaults with loaded config
    except FileNotFoundError:
        logging.warning("Config file not found. Using default configuration.")
        return DEFAULT_CONFIG

config = load_config()
NODE_ID = config["node_id"]
HEARTBEAT_INTERVAL = config["heartbeat_interval"]
ACK_TIMEOUT = config["ack_timeout"]
REBROADCAST_DELAY = config["rebroadcast_delay"]
MESSAGE_RETENTION = config["message_retention"]
CLUSTER_DISCOVERY_INTERVAL = config["cluster_discovery_interval"]
SLEEP_INTERVAL = config["sleep_interval"]

# Logging Setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class ClusterNode:
    def __init__(self):
        self.interface = meshtastic.serial_interface.SerialInterface()
        self.is_controller = False
        self.cluster_members = {}
        self.message_queue = {}
        self.node_message_history = {}
        self.received_messages = {}
        self.last_heartbeat = time.time()
        self.message_sequence = 0
        self.lock = threading.Lock()
        threading.Thread(target=self.heartbeat_loop, daemon=True).start()
        threading.Thread(target=self.message_listener, daemon=True).start()
        threading.Thread(target=self.message_checker, daemon=True).start()
        threading.Thread(target=self.cluster_discovery_loop, daemon=True).start()
        threading.Thread(target=self.sleep_mode, daemon=True).start()

    def elect_controller(self):
        self.cluster_members[NODE_ID] = time.time()
        controller_id = max(self.cluster_members.keys())
        self.is_controller = (controller_id == NODE_ID)
        logging.info(f"Node {NODE_ID}: Controller elected: {controller_id}")

    def send_heartbeat(self):
        self.interface.sendData(f"HEARTBEAT:{NODE_ID}")
        self.last_heartbeat = time.time()

    def heartbeat_loop(self):
        while True:
            self.send_heartbeat()
            time.sleep(HEARTBEAT_INTERVAL)

    def message_listener(self):
        while True:
            packet = self.interface.receive()
            if packet and "decoded" in packet and "text" in packet["decoded"]:
                message = packet["decoded"]["text"]
                sender_id = packet["from"]
                self.process_message(message, sender_id)

    def process_message(self, message, sender_id):
        try:
            if "HEARTBEAT:" in message:
                node_id = int(message.split(":")[1])
                with self.lock:
                    self.cluster_members[node_id] = time.time()
                    self.elect_controller()
            elif "MSG:" in message:
                message_parts = message.split(":")
                if len(message_parts) < 3:
                    raise ValueError("Invalid MSG format")
                message_id = message_parts[1]
                message_data = ":".join(message_parts[2:])
                with self.lock:
                    self.received_messages[message_id] = message_data
                    if sender_id not in self.node_message_history:
                        self.node_message_history[sender_id] = []
                    self.node_message_history[sender_id].append(message_id)
                    if len(self.node_message_history[sender_id]) > MESSAGE_RETENTION:
                        self.node_message_history[sender_id].pop(0)
                self.interface.sendData(f"ACK:{message_id}:{NODE_ID}", sender_id)
                if self.is_controller:
                    with self.lock:
                        if message_id not in self.message_queue:
                            self.message_queue[message_id] = {}
                        self.message_queue[message_id][sender_id] = time.time()
            elif "ACK:" in message:
                message_parts = message.split(":")
                message_id = message_parts[1]
                ack_node_id = int(message_parts[2])
                if self.is_controller:
                    with self.lock:
                        if message_id in self.message_queue:
                            self.message_queue[message_id][ack_node_id] = time.time()
            elif "REBROADCAST_REQ:" in message:
                message_id = message.split(":")[1]
                if self.is_controller:
                    if message_id in self.received_messages:
                        self.interface.sendData(f"MSG:{message_id}:{self.received_messages[message_id]}", sender_id)
            elif "CLUSTER_REQ:" in message:
                self.interface.sendData(f"CLUSTER_RESP:{NODE_ID}:{json.dumps(list(self.cluster_members.keys()))}", sender_id)
            elif "CLUSTER_RESP:" in message:
                sender_node = int(message.split(":")[1])
                neighbor_cluster = json.loads(message.split(":")[2])
                with self.lock:
                    for node in neighbor_cluster:
                        self.cluster_members[node] = time.time()

        except (ValueError, IndexError) as e:
            logging.error(f"Error processing message: {e}")

    def send_message(self, data):
        self.message_sequence += 1
        message_id = f"{NODE_ID}-{self.message_sequence}"
        self.interface.sendData(f"MSG:{message_id}:{data}")
        if self.is_controller:
            with self.lock:
                self.message_queue[message_id] = {NODE_ID: time.time()}

    def rebroadcast_check(self):
        if self.is_controller:
            current_time = time.time()
            with self.lock:
                for message_id, acks in self.message_queue.items():
                    for node_id in self.cluster_members:
                        if node_id != NODE_ID and node_id not in acks:
                            if current_time - acks.get(NODE_ID,0) > REBROADCAST_DELAY:
                                if message_id in self.received_messages:
                                    self.interface.sendData(f"MSG:{message_id}:{self.received_messages[message_id]}", node_id)
                                    acks[node_id] = current_time
    def message_checker(self):
        while True:
            time.sleep(1)
            self.rebroadcast_check()
            self.check_neighbor_messages()
            self.prune_messages()

  def check_neighbor_messages(self):
        with self.lock:  # Added the colon here
            for node_id, message_history in self.node_message_history.items():
                if node_id != NODE_ID:
                    for message_id in message_history:
                        if message_id not in self.received_messages:
                            self.interface.sendData(f"REBROADCAST_REQ:{message_id}", NODE_ID)
                          
    def prune_messages(self):
        current_time = time.time()
        with self.lock:
            messages_to_remove = []
            for message_id, acks in self.message_queue.items():
                all_acked = True
                for node_id in self.cluster_members:
                    if node_id not in acks:
                        all_acked = False
                        break
                if all_acked:
                    messages_to_remove.append(message_id)
            for message_id in messages_to_remove:
                del self.message_queue[message_id]
                if message_id in self.received_messages:
                    del self.received_messages[message_id]

    def cluster_discovery_loop(self):
        while True:
            self.interface.sendData("CLUSTER_REQ:")
            time.sleep(CLUSTER_DISCOVERY_INTERVAL)

    def sleep_mode(self):
      while True:
        time.sleep(SLEEP_INTERVAL)
        logging.info("Entering sleep mode")
        self.interface.close() #close the interface.
        time.sleep(10) #sleep for 10 seconds.
        self.interface = meshtastic.serial_interface.SerialInterface() #reopen interface.
        logging.info("Exiting sleep mode")
        with self.lock:
          self.cluster_members[NODE_ID] = time.time() #ensure node is still in cluster.

# Example Usage
node = ClusterNode()

# Example sending a message
if node.is_controller:
    node.send_message("Akita Meshtastic!")

# Keep the program running
while True:
    time.sleep(1)
