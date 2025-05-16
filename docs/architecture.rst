============
Architecture
============

The Akita Meshtastic Clustering System (AMCS) is a Python application designed to layer enhanced communication features on top of standard Meshtastic networks. It operates by managing its own message types over a dedicated Meshtastic port number.

High-Level Flow
---------------

1.  **Initialization:** Each AMCS node loads its configuration, initializes core components, and connects to the physical Meshtastic radio via the `NetworkInterface`.
2.  **Discovery & Election:** Nodes enter a `DISCOVERING` state, sending out `DISCOVERY_REQ` messages. If existing clusters with controllers are found, a node may attempt to join as a `MEMBER`. If no suitable controller is found, nodes may enter an `ELECTION` state to choose a `CONTROLLER` for a new cluster based on a term/voting mechanism.
3.  **Cluster Operation (Member):** As a `MEMBER`, a node sends its application data to its designated `CONTROLLER`. It receives cluster-wide broadcasts (including application data from other members) from its `CONTROLLER`. It sends `HEARTBEAT` messages and monitors the controller's heartbeats.
4.  **Cluster Operation (Controller):** As a `CONTROLLER`, a node receives application data from its `MEMBER`s (and can generate its own). It queues these messages, broadcasts them to all cluster members, and tracks acknowledgements (`ACK`s) from each member. It handles rebroadcasting messages to members that haven't ACKed. It also sends `HEARTBEAT` messages.
5.  **Reliability Mechanisms:**
    * **ACKs:** Direct messages and controller broadcasts are typically acknowledged to confirm receipt.
    * **Retries:** Direct messages have a retry mechanism with backoff if ACKs are not received.
    * **Controller Rebroadcasts:** Controllers resend messages to members who haven't ACKed.
    * **Neighbor Sync (Framework):** Nodes can exchange message history summaries (`SYNC_INFO`) and request specific missing messages (`MISSING_MSG_REQ`/`MRESP`) from peers to fill gaps.

Core Components
---------------

The system's functionality is primarily distributed across these Python modules within the ``src/akita_meshtastic_clustering/`` directory:

* **`Node` (`node.py`):** The central orchestrator. Manages node state (role), initializes components, runs the main event loop, handles role transitions, and dispatches messages. Provides `send_application_data()` for applications.

* **`NetworkInterface` (`network.py`):** Wraps `meshtastic-python` library calls. Handles radio connection, sending/receiving raw byte payloads over the AMCS port, and uses `pubsub` for Meshtastic events. **(API calls within need user verification)**.

* **`MessageHandler` (`messaging.py`):** Defines AMCS message types and structure. Handles message ID generation, ACK creation, duplicate detection (via recent ID history), direct ACK tracking/timeouts, and message payload storage (for Neighbor Sync responses). Manages the Controller's message queue.

* **`ClusterManager` (`cluster.py`):** Manages cluster discovery, neighbor tracking (via HEARTBEATs), controller election logic (term-based request/vote), joining/leaving clusters, and the Neighbor Synchronization process (initiating sync, processing sync messages).

* **`ControllerLogic` (`controller.py`):** Contains logic specific to the `CONTROLLER` role. Handles incoming messages from members, queues them (via `MessageHandler`), broadcasts to the cluster, processes ACKs from members, and manages rebroadcasts and queue pruning.

* **`PowerManager` (`power.py`):** Tracks node inactivity. Intended to trigger low-power modes via Meshtastic API calls. **(API calls need user implementation/verification)**.

* **`Config` (`config.py`):** Loads and validates node configuration from a JSON file, providing defaults.

* **`Utils` (`utils.py`):** Provides utility functions (e.g., `setup_logging`) and classes (e.g., `Timer`).

* **`Exceptions` (`exceptions.py`):** Defines custom AMCS exceptions for specific error conditions.

* **`Main` (`main.py`):** Entry point script. Parses arguments, sets up logging, initializes and runs the `Node`. Provides example application callbacks.

Key Message Types
-----------------

* `APP_DATA`: Carries application-specific payloads.
* `ACK`: Acknowledges receipt of a message.
* `HEARTBEAT`: Periodically broadcast by nodes to announce presence, role, cluster, and term.
* `DISCOVERY_REQ`: Broadcast by nodes in `DISCOVERING` state to find other nodes/clusters.
* `DISCOVERY_RESP`: Direct response to a `DISCOVERY_REQ` with the sender's status.
* `ELECTION_REQ`: Broadcast to initiate or participate in a controller election for a specific term.
* `ELECTION_VOTE`: Broadcast by a node casting its vote for a controller candidate in a specific term.
* `ELECTION_WINNER`: Broadcast by the newly elected controller to announce its status.
* `SYNC_REQ`: Sent by a node to a neighbor requesting its message history summary.
* `SYNC_INFO`: Sent by a node in response to `SYNC_REQ`, containing a summary of its recent messages (e.g., list of IDs).
* `MISSING_MSG_REQ`: Sent by a node to a neighbor requesting specific message payloads based on their IDs.
* `MISSING_MSG_RESP`: Sent by a node in response to `MISSING_MSG_REQ`, containing the requested message payloads (potentially chunked).
