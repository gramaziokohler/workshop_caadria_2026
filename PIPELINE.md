# Antikythera – Architectural Discussion Summary

## Context

Antikythera is a distributed fabrication orchestration system built around DAG-based blueprint execution, MQTT communication, and a claim/allocate/complete agent protocol. This document summarizes two architectural explorations discussed on top of the existing system.

---

## 1. Reactive Process Controller (State Machine Layer)

### The Core Idea

Lift the orchestrator from a **blueprint runner** to a **reactive process controller**. Blueprints become responses to events rather than the top-level thing being driven. The orchestrator becomes a long-lived process with a notion of state, rather than a one-shot executor.

### Key Concepts

- **States**: named states the system can be in (e.g. `IDLE`, `PICKING`, `WAITING_FOR_HUMAN`, `ERROR_RECOVERY`)
- **Events**: named triggers with optional data payloads (e.g. `element_selected`, `robot_failed`, `user_approved`)
- **Transitions**: `(current_state + event) → (action + next_state)`
- **Actions**: executing a blueprint (or sub-blueprint, or nothing)

Blueprint `START` and `END` become events in this system — `blueprint.started` and `blueprint.completed` (carrying output data as payload) can themselves trigger further transitions.

### What This Unlocks

- **Explicit looping**: states transition back to previous states on a condition, rather than implicit looping through blueprint composition
- **First-class fallback/recovery**: a `robot_failed` event transitions to `ERROR_RECOVERY` and triggers a recovery blueprint, decoupled from retry policies inside the blueprint
- **Human-in-the-loop**: a `WAITING_FOR_APPROVAL` state simply waits for an `approved`/`rejected` event — no special blueprint machinery needed
- **Reactive to external input**: anything that can publish an event (phone, sensor, Grasshopper component) can influence execution

### Architectural Position

This is a layer **above** the current orchestrator, not a replacement. The orchestrator continues to run blueprints as-is. The state machine is a new control plane that decides *which* blueprint to run *when*. The orchestrator's session lifecycle events feed back into the state machine as event sources.

This layer would need its own representation — tentatively called a **Process** or **Program** — defined in JSON first, Python DSL later, referencing blueprints by ID as transition actions. ImmuDB is a natural fit for Process state given its append-only nature: the event log *is* the state history.

### Open Questions

- Should a Process support parallel tracks (multiple concurrent active states), or always a single active state? Relevant for multi-robot scenarios.
- Are `blueprint.completed` and `blueprint.failed` one event or two? (Probably two, as they'd trigger different transitions.)
- Do events have a TTL or queue? If an event arrives mid-blueprint-execution, does it queue, get dropped, or preempt?

---

## 2. Grasshopper Agents in a Workshop Setting

### Context

A workshop where computational designers parametrically design a timber structure in Grasshopper, then robotically fabricate it. Two actors use their Grasshopper documents as Antikythera agents.

### The Two Actors

**Designer GH Agent** (`gh.design_authoring`)
- Hosts the parametric model — timber beam geometry, joint definitions, assembly sequence
- Receives a task from the orchestrator (possibly with constraints, e.g. available stock dimensions)
- When the designer is satisfied, they trigger task completion via a button, serializing the `compas_model` output into the session
- Pull model (orchestrator assigns the task) rather than push, so the orchestrator controls synchronization

**Fabricator GH Agent** (`gh.approve_trajectory`)
- Supervisory role — receives planned trajectories as task input data
- Visualizes trajectories in the GH viewport for human inspection before robot execution
- Approve/reject button sends task completion with a decision payload
- Maps directly onto the `needs_approval` concept from M2

The two GH documents never communicate with each other — both are agents in the same blueprint, mediated entirely by the orchestrator.

### Blueprint Flow (Sketch)

```
START
  └→ [gh.design_authoring]         # Designer GH: parametric model → compas_model output
       └→ [sequencer expansion]    # Orchestrator expands model into per-element sub-blueprints
            └→ for each element:
                 ├→ [planning.plan_trajectory]    # Planning agent: IK, collision-free path
                 ├→ [gh.approve_trajectory]       # Fabricator GH: visualize + approve/reject
                 └→ [rrc.execute_trajectory]      # RRC agent: send to robot
END
```

### Why This Is Interesting for a Workshop

- Participants see the session monitor progressing as they work — the process is externalized and legible
- The design-to-fabrication handoff is explicit and orchestrator-controlled, not a manual file export
- Two participants can genuinely collaborate: one designing, one approving at the robot cell
- Rejection or planning failure creates a natural hook for the state machine layer above

### Rough Edges to Address

- **Agent readiness**: GH agents must be running and connected to the broker before their tasks are assigned. A readiness handshake or pre-flight check may be needed for workshop robustness.
- **Rejection handling**: if the fabricator rejects a trajectory, the behavior needs to be defined — retry planning, skip element, pause session. This is a natural use case for the state machine layer even in a simple form.
- **Data volume**: passing full trajectory data through the session store (ImmuDB via compas_pb) for GH visualization may be heavy. Worth benchmarking early against realistic trajectory sizes.


# CAADRIA 2026 — Design-to-Fabrication Pipeline

Handoff document for continuing development with Claude Code.
Written April 8, 2026.

---

## Context

This workshop uses **Antikythera** as a distributed task orchestration system to connect
design, fabrication and robot execution across separate Grasshopper documents running on
different machines (or at least different Rhino instances).

Key libraries:
- **antikythera** — orchestrator, blueprint runner, session/data store (backed by immudb)
- **antikythera_agents** — `AgentLauncher`, `Agent` base class, `@agent`/`@tool` decorators
- **compas_eve** — MQTT pub/sub transport with protobuf codec (wraps paho-mqtt)
- **compas_ghpython** — `BackgroundWorker` for non-blocking GH components

Repos involved:
- `antikythera/` — orchestrator + agent framework
- `workshop_caadria_2026/` — this repo, workshop-specific GH components and pipeline
- `compas_eve/` — messaging transport (also in workspace for reference)

---

## What was built

### 1. Generic GH Agent component (`AKT_GH_Agent`)

**Location:** `antikythera/src/antikythera_ghpython/components/AKT_GH_Agent/`

A reusable Grasshopper Python component that makes any GH document a first-class
Antikythera agent. It implements the full agent protocol (claim → allocation → execute →
completion) by reusing `AgentLauncher` from `antikythera_agents`.

**How it works:**
- Uses `compas_eve.ghpython.BackgroundWorker` to keep Grasshopper reactive
- `run_agent()` runs on BackgroundWorker's thread, sets up `AgentLauncher` and returns
  immediately (`auto_set_done=False` keeps the worker alive)
- `_GrasshopperAgent` is a duck-typed class satisfying the `AgentLauncher` contract
- When the orchestrator assigns a task, `execute_task()` blocks on a `threading.Event`
  while storing the task data on the worker object
- `worker.update_result(task_data, delay=10)` triggers a GH solution re-solve via
  `compas_ghpython`'s timer mechanism (the correct way from a background thread)
- RunScript reads the pending task from the worker and exposes it as GH outputs
- When the user pulses `submit`, RunScript fires the event → `execute_task()` unblocks
  → returns the result dict → `AgentLauncher` publishes `TaskCompletionMessage`

**Key design decisions:**
- Subclass `AgentLauncher` overriding `_initialize_agents()` to skip plugin auto-discovery
- Store per-task state on the `BackgroundWorker` object (not `sc.sticky`) so it is
  naturally scoped to the worker lifetime
- Config change detection via `sc.sticky` forces a fresh worker if broker/task_type changes

**Component inputs:** `task_type`, `broker_host`, `broker_port`, `enabled`, `result`, `submit`
**Component outputs:** `task_id`, `inputs`, `params`, `output_keys`, `status`

---

### 2. Pipeline for the workshop

**Location:** `workshop_caadria_2026/grasshopper/pipeline/`

Three GH documents, one linear blueprint.

#### Shared agent module — `pipeline/gh_agent.py`

All pipeline GH agent components share a common module that provides:
- `GrasshopperAgent` — duck-typed class satisfying the `AgentLauncher` contract
  (task claiming, `execute_task` with `threading.Event` synchronization, etc.)
- `run_agent(component, worker, task_type, broker_host, broker_port, logger_name)` —
  sets up `AgentLauncher` on a BackgroundWorker thread
- `stop_agent(worker)` — dispose callback for `BackgroundWorker.stop_instance_by_component`
- `submit_result(worker, result_dict)` — unblocks the waiting `execute_task` thread

Each component's `code.py` imports from `gh_agent` via the `# env:` directive
(which adds the pipeline directory to `sys.path` at runtime in Rhino).

#### Blueprint: `pipeline/blueprint.json`

```
start → design.compute → fabrication.toolpaths → robot.mill → notify → end
```

Data flow through the session store (immudb):
- `design.compute` → sets `timber_model`
- `fabrication.toolpaths` → reads `timber_model`, sets `toolpaths`
- `robot.mill` → reads `toolpaths`, sets `milling_report`

#### Design agent — `pipeline/design/`

- Task type: `design.compute`
- Human role: tweak parameters, pulse **Submit** when happy
- Input from GH canvas: `timber_model` (whatever the design logic produces)
- Passes to session: `timber_model`
- Component message: *"task received — design!"*

#### Fabrication agent — `pipeline/fabrication/` + `pipeline/fabrication_submit/`

Split across **two GH components** to avoid a Grasshopper loop: the receiver
outputs `timber_model` for downstream toolpath generation, and the submitter
(placed downstream) accepts the computed `toolpaths` and sends them back.
They share the `BackgroundWorker` via `sc.sticky` keyed on `task_type`.

**Fabrication Receiver** (`pipeline/fabrication/`):
- Task type: `fabrication.toolpaths`
- Inputs: `task_type`, `broker_host`, `broker_port`, `enabled`
- Outputs: `task_id`, `timber_model`, `params`, `output_keys`, `status`
- Owns the BackgroundWorker and agent lifecycle
- Stores the worker in `sc.sticky["akt_fab_worker_{task_type}"]`

**Fabrication Submit** (`pipeline/fabrication_submit/`):
- Inputs: `task_type`, `toolpaths`, `submit`
- Outputs: `status`
- Looks up the shared worker from `sc.sticky`, calls `submit_result()`
- Component message: *"waiting for approval"* → *"submitted"*

**Why two components?** A single component that outputs `timber_model` and
accepts `toolpaths` as input would create a circular dependency in the GH
graph (a component downstream of itself). Splitting receiver from submitter
breaks the loop.

#### Robot agent — `pipeline/robot/`

- Task type: `robot.mill`
- Human role: safety check, then pulse **Submit** (or automate)
- Receives from session: `toolpaths` (exposed as component output, wire into robot driver)
- Passes to session: `milling_report`
- Component message: *"toolpaths received — ready to mill"*

---

## Pipeline conceptual rationale

The pipeline maps to **three disciplines** that mirror real DfAB workflows:

| Discipline | GH document | Agent | Human interaction |
|---|---|---|---|
| Design | design.gh | `design.compute` | Parametric control, approval |
| Fabrication | fabrication.gh | `fabrication.toolpaths` | Engineer review, approval gate |
| Robot | robot.gh | `robot.mill` | Safety check, execution |

**Why this structure for a workshop:**
- One blueprint file participants can read like a recipe (6 tasks, linear DAG)
- Each GH document has exactly one responsibility
- The "wow factor": change a joint angle in design.gh → press Submit → fabrication.gh
  automatically updates toolpaths → robot receives them without anyone touching it
- Intentionally left out: dynamic/sequencer tasks, competitive execution, conditional tasks

---

## What still needs to be done

### Immediate

- [ ] Wire up **actual design code** into `design/code.py`:
  the existing `01-rf_design.ghx` already produces a `TimberModel` with beams and joints,
  the agent just needs to wrap it
- [ ] Wire up **toolpath generation** into `fabrication/code.py`:
  `grasshopper/timber_toolpaths.py` already has `get_toolpath_from_lap_processing()` etc.,
  those need to consume the `timber_model` received from the session
- [ ] Wire up **robot execution** into `robot/code.py`:
  `grasshopper/robot.ghx` has existing robot cell setup, needs to accept toolpaths
  from the agent output

### Build / packaging

- [ ] Run `componentizer.py` against all three `pipeline/*/` directories to produce
  `.ghuser` files that participants can drop into Grasshopper
- [ ] Test the full pipeline end-to-end with the antikythera stack running
  (`docker compose up` in `antikythera/`)

### Data serialization (important)

The `timber_model`, `toolpaths` and `milling_report` values flow through antikythera's
session store as `compas_pb.data.AnyData` (protobuf). COMPAS objects serialize via the
COMPAS data framework (`__data__`/`from_data`). Verify that:
- `TimberModel` from `compas_timber` is COMPAS-serializable
- Toolpath objects (frames, polylines) are COMPAS primitives or wrapped properly
- If not, serialize to JSON/dict before putting them in the result dict

### Design iteration (iterate component)

The pipeline currently runs as a single pass. To allow the designer to iterate
on the model without restarting the session, an **Iterate** component was added.

**Location:** `pipeline/iterate_component/` (GH component) + `pipeline/iterate.py` (standalone helper)

**How it works — zero antikythera changes:**
The iterate component calls three existing orchestrator API endpoints in sequence:
1. `POST /sessions/{id}/pause` — stop the orchestrator (ignored if already stopped)
2. `POST /sessions/{id}/tasks/reset` — reset the `design` task and all downstream
   tasks to PENDING, clear their outputs from the session store
3. `POST /sessions/{id}/start` — resume the session; the scheduler re-dispatches
   `design.compute` to the design agent

**Component inputs:** `session_id`, `api_url` (default `http://localhost:8000`), `iterate` (button pulse)
**Component outputs:** `status`

The `blueprint_id` (`caadria-dfab`) and `task_id` (`design`) are hardcoded —
this is a workshop-specific component, not a generic tool.

**Workshop workflow:**
1. Start blueprint → design agent gets task → designer tweaks model → Submit
2. Pipeline runs through fabrication → robot → done
3. Designer modifies the model, presses **Iterate** → all tasks reset, session resumes
4. Design agent gets a new task → back to step 1

### Open question: assembly visualization

We discussed adding an **assembly.gh** that passively subscribes to session data and
visualizes the build sequence as beams are completed. This was intentionally left out
to keep the workshop simple but would be the natural fourth discipline.
Could be as simple as a `Ce_Subscribe` component on `antikythera/task/completed`
filtering for `robot.mill` task type.

---

## Running the stack

```bash
# 1. Start broker + orchestrator + immudb
cd antikythera/
docker compose up -d

# 2. In Rhino/Grasshopper: open design.gh, fabrication.gh, robot.gh
#    Set broker_host = "127.0.0.1", enabled = True on each agent component

# 3. Start a blueprint session (use the AKT_Start_Blueprint component or curl)
curl -X POST http://localhost:8000/blueprints/start \
  -H "Content-Type: application/json" \
  -d '{"blueprint_file": "grasshopper/pipeline/blueprint.json", "broker_host": "127.0.0.1"}'
```

---

## File index

```
workshop_caadria_2026/
  grasshopper/
    pipeline/
      blueprint.json                  ← orchestrator DAG
      gh_agent.py                     ← shared GrasshopperAgent, run/stop/submit helpers
      iterate.py                      ← standalone iterate helper (pause → reset → start)
      design/
        code.py                       ← Design agent GH component
        metadata.json
      fabrication/
        code.py                       ← Fabrication Receiver GH component
        metadata.json
      fabrication_submit/
        code.py                       ← Fabrication Submit GH component
        metadata.json
      robot/
        code.py                       ← Robot agent GH component
        metadata.json
      iterate_component/
        code.py                       ← Iterate button GH component
        metadata.json
    timber_toolpaths.py               ← existing toolpath generation code
    componentizer.py                  ← builds .ghuser files from code.py + metadata.json

antikythera/
  src/antikythera_ghpython/components/
    AKT_GH_Agent/
      code.py                         ← generic reusable GH agent base
      metadata.json
    AKT_Start_Blueprint/
      code.py                         ← starts a blueprint session via REST API
      metadata.json
  examples/
    test_gh_agent.json                ← minimal blueprint for testing AKT_GH_Agent
    caadria-dfab/                     ← alias: pipeline/blueprint.json
```
