=============
Configuration
=============

AMCS nodes are configured using a JSON file, typically named ``cluster_config.json``. By default, the main script looks for this file in the current working directory. You can specify a different path using the ``--config`` command-line argument when running ``main.py``.

If the configuration file is not found, or specific keys are missing, default values (defined in ``src/akita_meshtastic_clustering/config.py``) will be used. The exception is ``node_id``, which **must** be provided.

Configuration Parameters
------------------------

The following parameters can be set in the JSON file:

* ``node_id`` (integer | null):
    **Required.** A unique integer identifier for this specific AMCS node. Used for internal AMCS identification.
    Example: ``1001``

* ``meshtastic_port`` (string | null):
    Connection path to the Meshtastic device.
    * Serial: e.g., ``"/dev/ttyUSB0"`` (Linux), ``"COM3"`` (Windows).
    * TCP: e.g., ``"192.168.1.5"`` or ``"192.168.1.5:4403"``.
    Set to ``null`` (or omit) for serial auto-detect (can be less reliable).
    Default: ``null``.

* ``heartbeat_interval`` (float | integer):
    Interval in seconds for broadcasting HEARTBEAT messages.
    Default: ``60.0``.

* ``ack_timeout`` (float | integer):
    Time in seconds to wait for an ACK for directly addressed messages before retrying/failing.
    Default: ``15.0``.

* ``rebroadcast_delay`` (float | integer):
    Used by controller. Additional delay (seconds) after ``ack_timeout`` before considering rebroadcast to unacknowledged members.
    Default: ``5.0``.

* ``message_retention_count`` (integer):
    Max recent message IDs for duplicate detection. `<=0` effectively disables full ID-based duplicate checking.
    Default: ``100``.

* ``message_payload_retention_count`` (integer):
    Max message *payloads* stored for neighbor sync responses. `0` disables this storage.
    Default: ``200``. *(Neighbor Sync feature requires testing)*.

* ``message_payload_retention_seconds`` (float | integer):
    Max age (seconds) for stored payloads. `0` disables age-based pruning.
    Default: ``3600.0``. *(Neighbor Sync feature requires testing)*.

* ``cluster_discovery_interval`` (float | integer):
    Interval in seconds between DISCOVERY_REQ broadcasts when node is in ``DISCOVERING`` state.
    Default: ``120.0``.

* ``controller_timeout`` (float | integer):
    If ``MEMBER``, seconds without controller HEARTBEAT before assuming controller is lost. Also used as general neighbor activity timeout.
    Default: ``180.0``.

* ``election_timeout`` (float | integer):
    In ``ELECTION`` state, seconds to wait for votes/responses before restarting election for a higher term.
    Default: ``30.0``.

* ``sleep_interval`` (float | integer):
    Seconds of inactivity before node *considers* sleep mode. `0` disables. Actual sleep requires API implementation in ``power.py`` and hardware support.
    Default: ``300.0``.

* ``log_level`` (string):
    Logging verbosity: ``"DEBUG"``, ``"INFO"``, ``"WARNING"``, ``"ERROR"``, ``"CRITICAL"``. Case-insensitive.
    Default: ``"INFO"``.

* ``amcs_port_num`` (integer):
    Meshtastic PortNum for AMCS communication (valid range: 64-511). Must be same for all AMCS nodes.
    Default: From Meshtastic library's ``PRIVATE_APP`` or `4096` as fallback.

* ``meshtastic_hop_limit`` (integer):
    Default hop limit for outgoing Meshtastic packets sent by AMCS.
    Default: ``3``.

* ``meshtastic_channel_index`` (integer):
    Default channel index for outgoing Meshtastic packets sent by AMCS.
    Default: ``0``.

* ``sync_interval`` (float | integer):
    Seconds between initiating neighbor synchronization attempts (e.g., sending ``SYNC_REQ``).
    Default: ``180.0``. *(Neighbor Sync feature requires testing)*.

* ``max_missing_ids_per_req`` (integer):
    Maximum number of message IDs to request in a single ``MISSING_MSG_REQ`` during neighbor sync.
    Default: ``10``.

* ``max_msgs_per_resp`` (integer):
    Maximum number of full messages to include in a single ``MISSING_MSG_RESP`` chunk during neighbor sync.
    Default: ``3``.

* ``max_mresp_payload_bytes`` (integer):
    Estimated max byte size for the "msgs" list within an ``MRESP`` payload before chunking it into multiple packets. Should be conservative.
    Default: ``180``.

* ``neighbor_log_interval`` (float | integer):
    Seconds between logging the full status of known neighbors.
    Default: ``120.0``.

* ``stats_log_interval`` (float | integer):
    Seconds between logging the node's operational statistics. `0` or less disables periodic stats logging.
    Default: ``300.0``.


Example ``cluster_config.json``
-----------------------------

.. code-block:: json

    {
        "node_id": 1001,
        "meshtastic_port": "/dev/ttyUSB0",
        "heartbeat_interval": 45,
        "ack_timeout": 20,
        "controller_timeout": 200,
        "log_level": "DEBUG",
        "amcs_port_num": 4097,
        "sync_interval": 240
    }

*(Other parameters will use their defaults if omitted from the file)*
