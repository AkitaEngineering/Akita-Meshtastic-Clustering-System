=====
Usage
=====

This section describes how to run an AMCS node and general operational aspects.

Running a Node
--------------

1.  **Prerequisites:** Ensure you have completed all steps in the :doc:`installation` guide. This includes installing dependencies, creating a valid ``cluster_config.json`` file (with a unique ``node_id`` and correct ``meshtastic_port``), and crucially, **verifying/adapting the Meshtastic API calls** in ``src/akita_meshtastic_clustering/network.py``.
2.  **Activate Virtual Environment:** If you created one: ``source venv/bin/activate`` (or platform equivalent).
3.  **Navigate to Project Root:** Your terminal's current directory should be the root of the AMCS project.
4.  **Start the Node:**

    .. code-block:: bash

        python -m src.akita_meshtastic_clustering.main --config cluster_config.json

    You can also use the helper script (ensure it's executable: `chmod +x src/scripts/run_node.sh`):

    .. code-block:: bash

        ./src/scripts/run_node.sh path/to/your/cluster_config.json

    If you omit the path, `run_node.sh` defaults to `cluster_config.json` in the project root.

The node will then attempt to connect to the Meshtastic device specified in the configuration and begin its operational loop.

Monitoring Node Activity
------------------------

The primary way to monitor an AMCS node is via its **console log output**. The verbosity is controlled by the ``log_level`` parameter in ``cluster_config.json``:

* **DEBUG:** Extremely detailed, including raw-like message payloads, internal state checks, timer events. Best for active debugging.
* **INFO (Default):** Standard operational messages: startup, role changes, cluster joins, controller elections, timeouts, application data summaries, periodic statistics. Good for general monitoring.
* **WARNING/ERROR/CRITICAL:** Only problems and critical failures.

Key information to look for in logs:
* Successful connection to the Meshtastic radio and retrieved node information.
* Node role transitions: `INITIALIZING` -> `DISCOVERING` -> `ELECTION` -> (`MEMBER` or `CONTROLLER`).
* Assigned Cluster ID and current Controller AMCS ID.
* Sending/receiving of AMCS messages (HEARTBEAT, DISCOVERY, ELECTION, SYNC, ACK, APP_DATA).
* ACK timeouts, scheduled retries, and final send failures.
* Neighbor status updates (logged periodically by `ClusterManager`).
* Periodic statistics summaries from the `Node`.

Sending Application Data
------------------------

To send data using AMCS, your application needs to interact with an initialized `Node` instance. The `Node` class provides the `send_application_data(data)` method.

**Integration Note:** The provided `main.py` runs the `Node` in a blocking loop. For an external application to send data, you would typically:
1.  Run the AMCS `Node` in a separate thread or process.
2.  Obtain a reference to the `Node` instance in your main application thread/process.
3.  Call `amcs_node_instance.send_application_data(your_payload)`.

The example in `src/akita_meshtastic_clustering/main.py` demonstrates how to define and pass callbacks for receiving data and handling send failures:

.. code-block:: python

    # In your main application setup (conceptual, similar to main.py)
    from src.akita_meshtastic_clustering.node import Node

    def my_app_data_handler(app_payload: dict):
        logger.info(f"MyApp: Received Data: {app_payload}")
        # Process app_payload here

    def my_send_failure_handler(msg_id: str, destination: str, original_msg: dict):
        logger.error(f"MyApp: Failed to send msg {msg_id} to {destination}. Original: {original_msg['p']}")
        # Handle failure here

    amcs_node = Node(
        config_path="path/to/your_config.json",
        application_callback=my_app_data_handler,
        on_send_failure_callback=my_send_failure_handler
    )
    # Typically, you'd run amcs_node.run() in a thread.
    # Then, from another part of your app:
    # amcs_node.send_application_data({"temp": 25.5, "humidity": 60})

Receiving Application Data
--------------------------

When an AMCS node (typically a `MEMBER`) receives an `APP_DATA` message from its `CONTROLLER` (or a `CONTROLLER` processes its own `APP_DATA`), the extracted application payload is passed to the `application_callback` function. You define this callback when initializing the `Node` instance (see `main.py` for an example). Implement your application-specific logic within this callback.

Stopping a Node
---------------

Nodes can be stopped gracefully using:
* **Ctrl+C** in the terminal where the node is running.
* A **TERM signal** (e.g., from `kill <pid>` or system service managers).

The signal handler in `main.py` will catch these signals and trigger the `Node.shutdown()` method, which attempts to close network connections, cancel timers, and stop ongoing tasks cleanly.
