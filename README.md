# Co-Authoring Timber: Humans, Algorithms, and Robots 

[CAADRIA 2026 - Workshop B01](https://docs.google.com/document/d/1eJ9YbpuD04XLQwKufKgbBaLVxkBj4XfpUfleg1IdPAY/edit?tab=t.0#heading=h.gpx8jh4s9uxt)

![CAADRIA 2026](./images/caadria_ws_2026.png)

## Prerequisites

Please install the following two tools before the workshop. Use the official guides linked below — they walk you through every step.

### 1. Git
Downloads and keeps the workshop files up to date.
- **Mac:** [git-scm.com/download/mac](https://git-scm.com/download/mac)
- **Windows:** [git-scm.com/download/win](https://git-scm.com/download/win)

### 2. Docker Desktop
Runs the Antikythera Orchestrator and its dependencies. 
- **Mac & Windows:** [docs.docker.com/desktop/install](https://docs.docker.com/desktop/install/mac-install/) *(select your OS from the left sidebar)*

---

## Getting the Workshop Files

Once Git is installed, open **Terminal** (Mac) or **Command Prompt** (Windows) and run:

```
git clone https://github.com/gramaziokohler/workshop_caadria_2026.git
```

---

## Starting the Workshop Software

1. Make sure **Docker Desktop is open and running** (you should see the whale icon 🐳 in your menu/taskbar).
2. In your terminal, navigate into the workshop folder:
   ```
   cd workshop_caadria_2026
   ```  
3. Start all the containers:
   ```
   docker compose -f docker/docker-compose.yml up -d
   ```
4. Open your browser and go to **[http://localhost](http://localhost)** to access Antikythera interface.

To stop the containers when you're done:
```
docker compose -f docker/docker-compose.yml down
```

## Coding with VS Code

If you wish to use the provided libraries outside of Rhino/Grasshopper, these can be installed with `uv` and the provided `pyproject.toml` file.

- **Mac & Windows:** [docs.astral.sh/uv/getting-started/installation](https://docs.astral.sh/uv/getting-started/installation/#installation-methods) *(Follow the instructions for your OS)*

Then in the terminal, navigate to the workshop folder and run:
```
uv sync
```
