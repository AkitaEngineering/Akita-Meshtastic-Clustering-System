# Akita Meshtastic Clustering System (AMCS)


This repository contains the Akita Meshtastic Clustering System, a Meshtastic implementation designed to enhance message reliability, network robustness, and power efficiency.

## Overview

The Akita Meshtastic Clustering System addresses the challenges of unreliable message delivery in Meshtastic networks by implementing dynamic clustering, robust message queuing, and intelligent rebroadcasting. This system is designed for critical applications where message integrity and network resilience are paramount.

## Features

* **Dynamic Clustering:** Nodes automatically form and maintain clusters for localized reliability, adapting to changing network conditions.
* **Intelligent Controller Election:** A distributed algorithm ensures a stable and efficient cluster controller.
* **Robust Message Queuing:** Controllers maintain reliable message queues, ensuring messages are delivered even in challenging environments.
* **Comprehensive Acknowledgment (ACK) System:** Every message is acknowledged, guaranteeing delivery confirmation.
* **Adaptive Rebroadcasting:** Controllers strategically rebroadcast messages to nodes that have not acknowledged receipt, minimizing redundant transmissions.
* **Neighbor Message Synchronization:** Nodes actively compare message histories with neighbors, identifying and requesting missing messages.
* **Efficient Message Pruning:** Automatic pruning of message queues prevents resource exhaustion and maintains optimal performance.
* **Dynamic Cluster Discovery:** Nodes discover and join clusters in real-time, adapting to network changes.
* **Flexible Configuration:** Easy configuration via a JSON file (`cluster_config.json`).
* **Detailed Logging:** Comprehensive logging for monitoring and debugging.
* **Robust Error Handling:** Advanced error handling with timeouts and retries for increased reliability.
* **Meshtastic Security Integration:** Seamlessly leverages Meshtastic's built-in encryption.
* **Akita Power-Saving Mode:** Implements advanced sleep modes to minimize power consumption.
* **Input Validation:** message input is validated for stability.

## Getting Started

1.  **Prerequisites:**
    * Meshtastic device(s)
    * Python 3.6+
    * Meshtastic Python library (`pip install meshtastic`)

2.  **Installation:**
    * Clone this repository.
    * Install the required Python libraries.

3.  **Configuration:**
    * Create a `cluster_config.json` file in the repository's root directory.
    * Customize the configuration parameters as needed. Example:

    ```json
    {
        "node_id": 1234,
        "heartbeat_interval": 15,
        "ack_timeout": 7,
        "rebroadcast_delay": 3,
        "message_retention": 30,
        "cluster_discovery_interval": 60,
        "sleep_interval": 120
    }
    ```

    * If the `cluster_config.json` file is not found, default values will be used.

4.  **Running the Code:**
    * Run the `cluster_node.py` script on each Meshtastic node:

    ```bash
    python cluster_node.py
    ```

5.  **Monitoring:**
    * Monitor the logs for network activity and errors.

## Configuration Options

* `node_id`: Unique ID for the node.
* `heartbeat_interval`: Interval (in seconds) for sending heartbeat messages.
* `ack_timeout`: Timeout (in seconds) for acknowledgment messages.
* `rebroadcast_delay`: Delay (in seconds) before rebroadcasting messages.
* `message_retention`: Number of messages to retain in the queue.
* `cluster_discovery_interval`: interval in seconds that cluster discovery messages are sent.
* `sleep_interval`: interval in seconds that the node will enter a sleep state.

## Contributing

Akita Engineering welcomes contributions! Please submit pull requests or open issues for bug fixes, feature requests, or improvements.


## Future Enhancements (Akita Roadmap)

* Advanced power management strategies.
* Web-based configuration and monitoring interface.
* Scalable cluster management for large-scale deployments.
* Comprehensive test suite.
* Enhanced security protocols.
* GPS integration for location-aware applications.
* Advanced message filtering and routing.
* User-specific messaging and group management.
