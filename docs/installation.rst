============
Installation
============

Follow these steps to install the Akita Meshtastic Clustering System (AMCS).

Prerequisites
-------------

* **Hardware:** One or more Meshtastic-compatible devices flashed with recent firmware (ensure compatibility with the ``meshtastic-python`` library version used).
* **Python:** Python 3.7+ is recommended (check ``meshtastic-python`` requirements for specifics).
* **Git:** Required for cloning the repository.
* **meshtastic-python library:** This will be installed via ``requirements.txt``.

Steps
-----

1.  **Clone the Repository:**
    Open your terminal or command prompt and clone the AMCS repository from GitHub (replace with your actual repository URL):

    .. code-block:: bash

        git clone https://github.com/AkitaEngineering/Akita-Meshtastic-Clustering-System.git
        cd Akita-Meshtastic-Clustering-System

2.  **Set up Python Virtual Environment (Recommended):**
    It's highly recommended to use a virtual environment to manage dependencies for this project.

    .. code-block:: bash

        # Create the virtual environment (e.g., named 'venv')
        python -m venv venv

        # Activate the environment
        # On Linux/macOS:
        source venv/bin/activate
        # On Windows (cmd.exe):
        # venv\Scripts\activate.bat
        # On Windows (PowerShell):
        # venv\Scripts\Activate.ps1

    You should see ``(venv)`` prefixed on your command prompt line.

3.  **Install Dependencies:**
    Install the required Python libraries, including ``meshtastic``:

    .. code-block:: bash

        pip install -r requirements.txt

4.  **Configuration:**
    Before running a node, you need to configure it. See the :doc:`configuration` section for details. At minimum, you must:
    * Copy the example config: ``cp examples/cluster_config.json cluster_config.json`` (or your preferred location)
    * Edit your configuration file (e.g., ``cluster_config.json``) and set a **unique** integer ``node_id`` for each device.
    * Specify the ``meshtastic_port`` if needed (e.g., ``"/dev/ttyUSB0"`` or ``"192.168.1.5:4403"``).

5.  **Verify Meshtastic API Integration (CRUCIAL):**
    Before extensive testing, review and potentially adapt the code in:
    * ``src/akita_meshtastic_clustering/network.py``
    * ``src/akita_meshtastic_clustering/power.py``
    Ensure the API calls match your ``meshtastic-python`` library version. Pay attention to comments marked with ``--- API Assumption ---`` or ``**VERIFY API**``.

6.  **Run Unit Tests (Optional but Recommended):**
    Run the basic unit tests to check core utilities:

    .. code-block:: bash

        python -m unittest discover tests

You are now ready to run an AMCS node. See the :doc:`usage` section. Remember to ``deactivate`` the virtual environment when done.
