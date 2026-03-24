"""
MiroFish swarm-intelligence simulation client.

Actual MiroFish API workflow (discovered from source):
  1. POST /api/graph/ontology/generate  — upload seed material, create project
  2. POST /api/graph/build              — build knowledge graph
  3. POST /api/simulation/create        — create simulation from project+graph
  4. POST /api/simulation/prepare       — generate agent profiles
  5. POST /api/simulation/start         — run OASIS simulation
  6. GET  /api/simulation/{id}/run-status — monitor progress
  7. POST /api/report/generate          — generate prediction report
  8. GET  /api/report/{report_id}       — retrieve report
"""

import io
import logging
import re
import time

import requests
from openai import OpenAI

from src.config import Config

log = logging.getLogger(__name__)

MAX_SIM_COST = 5.00


class MiroFishClient:
    """Client for the MiroFish swarm intelligence backend."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.base_url = config.mirofish_backend_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Accept": "application/json"})

        self._llm = OpenAI(
            api_key=config.llm_api_key or "not-needed",
            base_url=config.llm_base_url,
        )
        self._llm_model = config.llm_model_name

    # ── Health ───────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        try:
            resp = self.session.get(f"{self.base_url}/api/graph/project/list", timeout=10)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    # ── Step 1: Upload seed material & create project ────────────────────

    def create_project(self, seed_text: str, project_name: str = None) -> dict:
        """Upload seed material and generate ontology. Returns project data with project_id."""
        if not project_name:
            project_name = f"sim_{int(time.time())}"

        # Send seed text as a file upload
        files = {
            "files": ("seed_material.md", io.BytesIO(seed_text.encode("utf-8")), "text/markdown"),
        }
        data = {
            "simulation_requirement": seed_text[:500],
            "project_name": project_name,
        }

        resp = self.session.post(
            f"{self.base_url}/api/graph/ontology/generate",
            files=files,
            data=data,
            timeout=300,  # LLM call can take 2-3 min via Claude CLI gateway
        )
        resp.raise_for_status()
        result = resp.json()

        if not result.get("success"):
            raise RuntimeError(f"Project creation failed: {result.get('error', result)}")

        project_data = result.get("data", {})
        log.info("Project created: %s (id=%s)", project_name, project_data.get("project_id"))
        return project_data

    # ── Step 2: Build knowledge graph ────────────────────────────────────

    def build_graph(self, project_id: str) -> str:
        """Build knowledge graph from project. Returns task_id."""
        resp = self.session.post(
            f"{self.base_url}/api/graph/build",
            json={"project_id": project_id},
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()

        if not result.get("success"):
            raise RuntimeError(f"Graph build failed: {result.get('error', result)}")

        task_id = result["data"].get("task_id")
        log.info("Graph build started: task=%s", task_id)
        return task_id

    def wait_for_graph(self, task_id: str, timeout: int = 300) -> str:
        """Poll graph build task until complete. Returns graph_id."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = self.session.get(
                    f"{self.base_url}/api/graph/task/{task_id}",
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json().get("data", resp.json())
                status = data.get("status", "unknown")

                if status in ("completed", "done", "success"):
                    graph_id = data.get("graph_id") or data.get("result", {}).get("graph_id")
                    log.info("Graph build completed: graph=%s", graph_id)
                    return graph_id
                if status in ("failed", "error"):
                    raise RuntimeError(f"Graph build failed: {data}")
            except requests.RequestException as e:
                log.warning("Graph task check failed: %s", e)
            time.sleep(5)

        raise TimeoutError(f"Graph build timed out after {timeout}s")

    # ── Step 3: Create simulation ────────────────────────────────────────

    def create_simulation(self, project_id: str, graph_id: str = None) -> str:
        """Create a simulation from project. Returns simulation_id."""
        payload = {
            "project_id": project_id,
            "enable_twitter": True,
            "enable_reddit": False,  # twitter-only for speed
        }
        if graph_id:
            payload["graph_id"] = graph_id

        resp = self.session.post(
            f"{self.base_url}/api/simulation/create",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        if not result.get("success"):
            raise RuntimeError(f"Simulation creation failed: {result.get('error', result)}")

        sim_id = result["data"].get("simulation_id")
        log.info("Simulation created: %s", sim_id)
        return sim_id

    # ── Step 4: Prepare (generate agent profiles) ────────────────────────

    def prepare_simulation(self, sim_id: str) -> str:
        """Generate agent profiles. Returns task_id."""
        resp = self.session.post(
            f"{self.base_url}/api/simulation/prepare",
            json={
                "simulation_id": sim_id,
                "use_llm_for_profiles": True,
                "parallel_profile_count": 5,
            },
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()

        if not result.get("success"):
            raise RuntimeError(f"Simulation prepare failed: {result.get('error', result)}")

        task_id = result["data"].get("task_id")
        log.info("Simulation preparation started: task=%s", task_id)
        return task_id

    def wait_for_preparation(self, sim_id: str, timeout: int = 600) -> bool:
        """Poll preparation status until ready."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = self.session.post(
                    f"{self.base_url}/api/simulation/prepare/status",
                    json={"simulation_id": sim_id},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json().get("data", resp.json())
                status = data.get("status", "unknown")

                if status in ("completed", "done", "ready"):
                    log.info("Simulation preparation completed for %s", sim_id)
                    return True
                if status in ("failed", "error"):
                    log.error("Preparation failed for %s: %s", sim_id, data)
                    return False
            except requests.RequestException as e:
                log.warning("Prep status check failed: %s", e)
            time.sleep(10)

        log.warning("Preparation timed out for %s", sim_id)
        return False

    # ── Step 5: Start simulation ─────────────────────────────────────────

    def start_simulation(self, sim_id: str, max_rounds: int = None) -> bool:
        """Launch the OASIS simulation."""
        payload = {
            "simulation_id": sim_id,
            "platform": "twitter",  # twitter-only is 2x faster than parallel, sufficient for binary predictions
        }
        if max_rounds:
            payload["max_rounds"] = max_rounds

        resp = self.session.post(
            f"{self.base_url}/api/simulation/start",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()

        if not result.get("success"):
            raise RuntimeError(f"Simulation start failed: {result.get('error', result)}")

        log.info("Simulation started: %s", sim_id)
        return True

    def get_simulation_status(self, sim_id: str) -> str:
        """Get simulation run status. Returns 'running', 'completed', 'failed', etc."""
        try:
            resp = self.session.get(
                f"{self.base_url}/api/simulation/{sim_id}/run-status",
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("data", resp.json())
            status = data.get("runner_status") or data.get("status", "unknown")
            return status
        except requests.RequestException as e:
            log.warning("Status check failed for %s: %s", sim_id, e)
            return "unknown"

    def wait_for_completion(self, sim_id: str, timeout: int = 1800) -> bool:
        """Poll until simulation completes. Default 30 min timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.get_simulation_status(sim_id)
            if status in ("completed", "stopped", "done"):
                log.info("Simulation %s completed", sim_id)
                return True
            if status in ("failed", "error"):
                log.error("Simulation %s failed", sim_id)
                return False
            log.debug("Simulation %s status: %s (%.0fs remaining)",
                      sim_id, status, deadline - time.monotonic())
            time.sleep(15)

        log.warning("Simulation %s timed out after %ds", sim_id, timeout)
        return False

    # ── Step 6: Generate & retrieve report ───────────────────────────────

    def generate_report(self, sim_id: str) -> str:
        """Trigger report generation. Returns report_id."""
        resp = self.session.post(
            f"{self.base_url}/api/report/generate",
            json={"simulation_id": sim_id},
            timeout=120,
        )
        resp.raise_for_status()
        result = resp.json()

        if not result.get("success"):
            raise RuntimeError(f"Report generation failed: {result.get('error', result)}")

        report_id = result["data"].get("report_id")
        log.info("Report generation started: %s", report_id)
        return report_id

    def wait_for_report(self, report_id: str, timeout: int = 600) -> bool:
        """Poll report generation status."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = self.session.get(
                    f"{self.base_url}/api/report/generate/status?report_id={report_id}",
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json().get("data", resp.json())
                status = data.get("status", "unknown")

                if status in ("completed", "done"):
                    return True
                if status in ("failed", "error"):
                    return False
            except requests.RequestException:
                pass
            time.sleep(10)
        return False

    def get_report(self, report_id: str) -> dict:
        """Retrieve the completed report."""
        resp = self.session.get(
            f"{self.base_url}/api/report/{report_id}",
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        return result.get("data", result)

    def get_report_by_simulation(self, sim_id: str) -> dict:
        """Get report by simulation ID."""
        resp = self.session.get(
            f"{self.base_url}/api/report/by-simulation/{sim_id}",
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
        return result.get("data", result)

    # ── Probability Extraction ───────────────────────────────────────────

    def extract_probability(self, report: dict, event_question: str) -> float:
        """Use LLM to extract a 0.0-1.0 probability from the report."""
        report_text = report.get("markdown_content") or _flatten_report(report)

        prompt = (
            "You are extracting the crowd consensus probability from a multi-agent "
            "social simulation report. The simulation ran 1000+ AI agents who debated "
            "and discussed this event from diverse perspectives.\n\n"
            f"EVENT QUESTION: {event_question}\n\n"
            f"SIMULATION REPORT:\n{report_text[:8000]}\n\n"
            "Based ONLY on what the simulated agents concluded — their posts, "
            "discussions, sentiment trends, and any voting or consensus data in "
            "the report — what percentage of agents believed the answer is YES?\n\n"
            "Important:\n"
            "- Extract the AGENTS' consensus, not your own opinion\n"
            "- If 60% of agent posts were supportive/bullish, output 0.60\n"
            "- If agents were evenly split, output near 0.50\n"
            "- If the report lacks clear sentiment data, output 0.50\n"
            "- Do NOT default to low probabilities just because an event seems unlikely\n\n"
            "Respond with ONLY a single decimal number between 0.05 and 0.95. Nothing else."
        )

        response = self._llm.chat.completions.create(
            model=self._llm_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=10,
        )

        raw = response.choices[0].message.content.strip()
        match = re.search(r"(\d+\.?\d*)", raw)
        if not match:
            log.error("LLM returned non-numeric probability: %r", raw)
            return 0.50

        prob = float(match.group(1))
        prob = max(0.01, min(0.99, prob))
        log.info("Extracted probability %.4f for: %s", prob, event_question[:80])
        return prob

    # ── Cost Estimation ──────────────────────────────────────────────────

    def estimate_cost(self, agent_count: int = None, rounds: int = None) -> float:
        agent_count = agent_count or self.config.mirofish_agent_count
        rounds = rounds or self.config.mirofish_rounds
        return agent_count * rounds * 0.0001


def _flatten_report(report: dict) -> str:
    """Convert a report dict into readable text for the LLM prompt."""
    parts = []
    def _walk(obj, prefix=""):
        if isinstance(obj, dict):
            for key, val in obj.items():
                _walk(val, f"{prefix}{key}: ")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{prefix}[{i}] ")
        else:
            parts.append(f"{prefix}{obj}")
    _walk(report)
    return "\n".join(parts)


def run_full_simulation(client: MiroFishClient, seed_text: str, event_question: str,
                        agent_count: int = None, rounds: int = None) -> dict:
    """Run the complete MiroFish simulation pipeline.

    Steps: create project → build graph → create sim → prepare → start → report → extract probability
    """
    rounds = rounds or client.config.mirofish_rounds

    try:
        # Step 1: Create project & ontology
        project = client.create_project(seed_text)
        project_id = project.get("project_id")
        if not project_id:
            return {"sim_id": None, "status": "failed", "probability": None,
                    "report": None, "estimated_cost": 0, "error": "No project_id returned"}

        # Step 2: Build knowledge graph
        task_id = client.build_graph(project_id)
        graph_id = client.wait_for_graph(task_id, timeout=300)

        # Step 3: Create simulation
        sim_id = client.create_simulation(project_id, graph_id)

        # Step 4: Prepare agent profiles
        client.prepare_simulation(sim_id)
        prepared = client.wait_for_preparation(sim_id, timeout=600)
        if not prepared:
            return {"sim_id": sim_id, "status": "prep_failed", "probability": None,
                    "report": None, "estimated_cost": client.estimate_cost(rounds=rounds)}

        # Step 5: Start simulation
        client.start_simulation(sim_id, max_rounds=rounds)
        completed = client.wait_for_completion(sim_id, timeout=1800)
        if not completed:
            return {"sim_id": sim_id, "status": "timeout", "probability": None,
                    "report": None, "estimated_cost": client.estimate_cost(rounds=rounds)}

        # Step 6: Generate and retrieve report
        report_id = client.generate_report(sim_id)
        client.wait_for_report(report_id, timeout=600)
        report = client.get_report(report_id)

        # Step 7: Extract probability
        probability = client.extract_probability(report, event_question)

        return {
            "sim_id": sim_id,
            "status": "completed",
            "probability": probability,
            "report": report,
            "estimated_cost": client.estimate_cost(rounds=rounds),
        }

    except Exception as e:
        log.error("Simulation pipeline failed: %s", e)
        return {"sim_id": None, "status": "failed", "probability": None,
                "report": None, "estimated_cost": 0, "error": str(e)}
