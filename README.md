# Akita Meshtastic Clustering System (AMCS)

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

Developed by [Akita Engineering](https://www.akitaengineering.com) | Current Date: May 16, 2025

---

** IMPORTANT: DEVELOPMENT STATUS & REQUIRED ACTIONS **

This codebase provides a **comprehensive framework** for the Akita Meshtastic Clustering System. However, it is **NOT yet ready for production deployment.**

Before use, you **MUST**:
1.  **Verify and Adapt Meshtastic API Calls:** The interactions with the `meshtastic-python` library in `src/akita_meshtastic_clustering/network.py` and `src/akita_meshtastic_clustering/power.py`  **must be verified and potentially modified** to match your specific `meshtastic-python` library version and hardware capabilities.
2.  **Perform Thorough Hardware Testing:** This system requires extensive testing on actual Meshtastic devices in your target network environment to identify bugs, tune parameters, and ensure stability and reliability.
3.  **Review Neighbor Synchronization Implementation:** While the framework and basic logic for neighbor message synchronization are in place, including message storage and response chunking, its real-world performance and edge cases need extensive validation and potential refinement if this feature is critical.

---

## Overview

The Akita Meshtastic Clustering System (AMCS) is a Python-based application designed to run on devices using Meshtastic radios. It enhances standard Meshtastic networks by implementing dynamic clustering, reliable message queuing via a controller, intelligent rebroadcasting, and mechanisms for improved data consistency among nodes. The primary goals are to increase message delivery reliability, network robustness, and potentially power efficiency for critical applications.

## Core Features

* **Dynamic Clustering:** Nodes automatically attempt to discover and join or form local clusters.
* **Controller Election:** A term-based request/vote mechanism allows nodes to elect a cluster controller.
* **Reliable Queuing & Broadcasting (Controller):** The elected controller queues messages received from members and broadcasts them to the cluster, managing acknowledgements.
* **Acknowledgement System:** Nodes send ACKs for received messages to enable reliability tracking.
* **Adaptive Rebroadcasting (Controller):** The controller can rebroadcast messages to members that have not acknowledged receipt.
* **Non-Blocking Retries:** Direct messages use non-blocking retries with exponential backoff for ACK timeouts.
* **Neighbor Message Synchronization:**
    * Nodes can exchange summaries of their message histories (`SYNC_INFO`, `SYNC_REQ`).
    * Nodes can request specific missing messages (`MISSING_MSG_REQ`).
    * Nodes can respond with requested messages, including payload chunking (`MISSING_MSG_RESP`).
    * Message payload storage for sync responses is implemented in `MessageHandler`.
* **Statistics Tracking:** Nodes collect and periodically log operational statistics (messages sent/received, ACKs, timeouts, etc.).
* **Application Callbacks:** Provides hooks for your application to receive processed data and be notified of permanent send failures.
* **Power Saving (Placeholder):** Includes logic for considering low-power modes based on inactivity; requires specific Meshtastic API implementation in `power.py`.
* **Flexible Configuration:** Node behavior is customized via a `cluster_config.json` file.
* **Modular Design:** Code is organized into logical components for easier understanding and maintenance.
* **Documentation:** Includes inline docstrings and a Sphinx documentation structure in `docs/`.
* **Unit Tests (Basic):** Initial unit tests for core utilities and message handling basics.

## Getting Started

### Prerequisites

* **Hardware:** One or more Meshtastic-compatible devices (e.g., ESP32-based boards like T-Beam, Heltec) flashed with recent Meshtastic firmware. Ensure firmware is compatible with the `meshtastic-python` library version you use.
* **Python:** Python 3.7+ is recommended. Check the specific requirements of the `meshtastic-python` library.
* **Git:** For cloning the repository.
* **Meshtastic Python Library:** This will be installed via `requirements.txt`.

### Installation

1.  **Clone the Repository:**
    ```bash
    git clone [https://github.com/akitaengineering/Akita-Meshtastic-Clustering-System.git](https://github.com/akitaengineering/Akita-Meshtastic-Clustering-System.git) 
    cd Akita-Meshtastic-Clustering-System
    ```

2.  **Set up a Python Virtual Environment (Highly Recommended):**
    ```bash
    python -m venv venv
    # On Linux/macOS:
    source venv/bin/activate
    # On Windows (cmd.exe):
    # venv\Scripts\activate.bat
    # On Windows (PowerShell):
    # .\venv\Scripts\Activate.ps1
    ```
    Your command prompt should now be prefixed with `(venv)`.

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Verify/Adapt Meshtastic API Calls (Crucial):**
    Before running, carefully review and adapt the code in:
    * `src/akita_meshtastic_clustering/network.py`
    * `src/akita_meshtastic_clustering/power.py`
    Ensure the API calls match your `meshtastic-python` library version. Pay attention to comments marked with `--- API Assumption ---` or `**VERIFY API**`.

### Configuration

1.  **Copy Example Configuration:**
    ```bash
    cp examples/cluster_config.json cluster_config.json
    ```
    This creates `cluster_config.json` in the project root.

2.  **Edit `cluster_config.json`:**
    * **`node_id` (Required):** Set a **unique integer** for each device running AMCS.
    * **`meshtastic_port`:** Specify your device's serial port (e.g., `/dev/ttyUSB0`, `COM3`) or TCP address (e.g., `192.168.1.X:4403`). Set to `null` for serial auto-detect (can be unreliable).
    * Adjust other parameters (timeouts, intervals, logging level) as needed. See [Configuration Options](#configuration-options) below for details.

### Running a Node

Ensure your Meshtastic device is connected to your computer/SBC.

From the **project root directory** (the one containing `src/`, `docs/`, etc.):

```bash
python -m src.akita_meshtastic_clustering.main --config cluster_config.json
```
Alternatively, use the provided shell script (ensure it's executable: chmod +x src/scripts/run_node.sh):

```Bash

./src/scripts/run_node.sh cluster_config.json # You can optionally pass config path
```
The node will start, attempt to connect to the Meshtastic radio, and log its activities to the console. Monitor these logs closely, especially during initial testing.

### Configuration Options (`cluster_config.json`)
All parameters are optional *except `node_id`*. Defaults are used if a key is missing.

* `node_id` (int | null): **Required.** Unique integer for this AMCS node.
* `meshtastic_port` (str | null): Connection path to the Meshtastic device (e.g., `/dev/ttyUSB0`, `192.168.1.5:4403`). `null` for serial auto-detect. Default: `null`.
* `heartbeat_interval` (float | int): Seconds between sending HEARTBEAT messages. Default: `60.0`.
* `ack_timeout` (float | int): Seconds to wait for an ACK for direct messages before retrying. Default: `15.0`.
* `rebroadcast_delay` (float | int): Additional seconds after ACK timeout for controller to consider rebroadcasting. Default: `5.0`.
* `message_retention_count` (int): Max recent message IDs for duplicate detection. `<=0` disables. Default: `100`.
* `message_payload_retention_count` (int): Max message payloads stored for neighbor sync responses. `0` disables storage. Default: `200`.
* `message_payload_retention_seconds` (float | int): Max age (seconds) for stored payloads. `0` disables age-based pruning. Default: `3600.0`.
* `cluster_discovery_interval` (float | int): Seconds between DISCOVERY_REQ broadcasts when in DISCOVERING state. Default: `120.0`.
* `controller_timeout` (float | int): Seconds without controller HEARTBEAT before member assumes lost. Also used for neighbor timeout. Default: `180.0`.
* `election_timeout` (float | int): Seconds to wait for election votes before restarting election. Default: `30.0`.
* `sleep_interval` (float | int): Seconds of inactivity before *considering* sleep. `0` disables. Requires API implementation. Default: `300.0`.
* `log_level` (str): Logging verbosity: "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL". Default: "INFO".
* `amcs_port_num` (int): Meshtastic PortNum for AMCS (64-511). Default: `4096` (or library's `PRIVATE_APP`).
* `meshtastic_hop_limit` (int): Hop limit for outgoing Meshtastic packets. Default: `3`.
* `meshtastic_channel_index` (int): Channel index for Meshtastic packets. Default: `0`.
* `sync_interval` (float | int): Seconds between initiating neighbor sync attempts. Default: `180.0`.
* `max_missing_ids_per_req` (int): Max IDs to request in one `MISSING_MSG_REQ`. Default: `10`.
* `max_msgs_per_resp` (int): Max full messages per `MISSING_MSG_RESP` chunk. Default: `3`.
* `max_mresp_payload_bytes` (int): Estimated max byte size for the "msgs" list in an `MRESP` payload before chunking. Default: `180`.
* `neighbor_log_interval` (float | int): Seconds between logging neighbor status list. Default: `120.0`.
* `stats_log_interval` (float | int): Seconds between logging the node's operational statistics. `0` or less disables periodic stats logging. Default: `300.0`.

### Monitoring and Debugging
* **Logs:** The primary tool. Set `log_level: "DEBUG"` in `cluster_config.json` for maximum detail. Logs include timestamps, module names, roles, cluster IDs, and message details.
* **Statistics:** The node periodically logs operational statistics (message counts, timeouts, etc.).
* **Neighbor Status:** Logged periodically, showing known neighbors and their last seen times.

### Testing
* **Unit Tests:** Basic unit tests for some utilities and message handling logic are in the `tests/` directory. Run them from the project root:
    ```bash
    python -m unittest discover tests
    ```
* **Hardware Integration Testing (Essential):**
    1.  Start with 2-3 nodes.
    2.  Verify connection to radios and correct node ID display in logs.
    3.  Observe discovery, election, and cluster formation.
    4.  Test application data sending from a member and confirm receipt (via `application_callback`) on other members.
    5.  Check ACK behavior and controller rebroadcasts (may require temporarily interfering with a node).
    6.  Test controller failover by stopping the controller node and observing re-election.
    7.  Test neighbor synchronization if that feature is critical for your use case.
    8.  Gradually increase the number of nodes and network complexity.
    9.  Tune configuration parameters (especially timeouts) based on observed behavior.

### Documentation
Detailed documentation can be generated from the `docs/` directory using Sphinx. You will need to install Sphinx and a theme (e.g., `sphinx_rtd_theme`):

```bash
pip install sphinx sphinx_rtd_theme
```
Then, from the project root directory, build the HTML documentation:
```Bash
sphinx-build -b html docs docs/_build
```
Open `docs/_build/html/index.html` in your browser.

### Contributing
Contributions are welcome! Please feel free to submit Pull Requests for bug fixes, feature enhancements, or improvements. For major changes, please open an Issue first to discuss the proposed changes.

### Future Enhancements (Roadmap Ideas)
* Robust Meshtastic API Integration: Continuously verify and improve `network.py` and `power.py`.
* Advanced Power Management: Implement and test deep sleep modes using verified Meshtastic API calls.
* Web Interface: A local web UI for configuration, status monitoring, and sending messages.
* Scalability Optimizations: Test and optimize for larger numbers of nodes/clusters.
* Comprehensive Test Suite: Expand unit tests and develop integration tests.
* Security: Additional security layers beyond Meshtastic encryption if needed.
* GPS Integration: Use location data for smarter clustering or location-aware features.
* More Robust Election Algorithm: If the current election proves insufficient, explore elements from more advanced consensus protocols.

### License
This project is licensed under the GNU General Public License v3.0. See the `LICENSE` file for the full license text.

Copyright (c) 2025 Akita Engineering.


