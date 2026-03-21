"""
MiroFish swarm-intelligence simulation client.

Communicates with the MiroFish Flask backend at :5001.
Actual API endpoints (from MiroFish source/docs):
  - POST /api/project/create        — create a new project
  - POST /api/project/upload         — upload seed material
  - POST /api/simulation/create      — create simulation from project graph
  - POST /api/simulation/prepare     — generate agent profiles
  - GET  /api/simulation/prepare/status
  - POST /api/simulation/start       — launch OASIS subprocess
  - GET  /api/simulation/status      — poll execution state
  - POST /api/simulation/stop        — stop simulation
  - POST /api/report/generate        — trigger ReACT report agent
  - POST /api/report/chat            — chat with report agent
  - GET  /api/report/logs            — get report logs
  - GET  /health                     — health check
"""

import logging
import re
import time

import requests
from openai import OpenAI

from src.config import Config

log = logging.getLogger(__name__)

MAX_SIM_COST = 5.00  # USD — refuse simulations above this


class MiroFishClient:
    """Client for the MiroFish swarm intelligence backend."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.base_url = config.mirofish_backend_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        # OpenAI-compatible LLM for probability extraction
        self._llm = OpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
        )
        self._llm_model = config.llm_model_name

    # ── Health ───────────────────────────────────────────────────────────

    def health_check(self) -> bool:
        """Return True if the MiroFish backend is healthy."""
        try:
            resp = self.session.get(f"{self.base_url}/health", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    # ── Project Setup ────────────────────────────────────────────────────

    def create_project(self, name: str, description: str = "") -> dict:
        """Create a new MiroFish project."""
        resp = self.session.post(
            f"{self.base_url}/api/project/create",
            json={"name": name, "description": description},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        log.info("Project created: %s", name)
        return data

    def upload_seed_text(self, seed_text: str, filename: str = "seed.md") -> dict:
        """Upload seed material as a document to the current project."""
        resp = self.session.post(
            f"{self.base_url}/api/project/upload",
            files={"file": (filename, seed_text, "text/markdown")},
            headers={},  # let requests set multipart content-type
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        log.info("Seed material uploaded: %s", filename)
        return data

    # ── Simulation Lifecycle ─────────────────────────────────────────────

    def create_simulation(
        self,
        seed_text: str,
        agent_count: int | None = None,
        rounds: int | None = None,
    ) -> str:
        """Full workflow: create project -> upload seed -> create simulation.

        Returns a simulation ID string.
        """
        agent_count = agent_count or self.config.mirofish_agent_count
        rounds = rounds or self.config.mirofish_rounds

        # Cost guard
        cost = self.estimate_cost(agent_count, rounds)
        if cost > MAX_SIM_COST:
            raise ValueError(
                f"Estimated cost ${cost:.2f} exceeds MAX_SIM_COST ${MAX_SIM_COST:.2f}. "
                f"Reduce agent_count ({agent_count}) or rounds ({rounds})."
            )

        # Step 1: Create project
        project_name = f"sim_{int(time.time())}"
        self.create_project(project_name, seed_text[:200])

        # Step 2: Upload seed material
        self.upload_seed_text(seed_text)

        # Step 3: Create simulation from project graph
        try:
            resp = self.session.post(
                f"{self.base_url}/api/simulation/create",
                json={"agent_count": agent_count, "rounds": rounds},
                timeout=30,
            )
        except requests.ConnectionError as exc:
            raise ConnectionError(
                f"MiroFish backend unreachable at {self.base_url}. "
                f"Is the server running? Detail: {exc}"
            ) from exc

        if not resp.ok:
            raise RuntimeError(
                f"MiroFish create_simulation failed: "
                f"HTTP {resp.status_code} — {resp.text[:500]}"
            )

        data = resp.json()
        sim_id = data.get("simulation_id") or data.get("id") or project_name
        log.info("Simulation created: %s (agents=%d, rounds=%d, est=$%.2f)",
                 sim_id, agent_count, rounds, cost)
        return str(sim_id)

    def prepare_simulation(self, sim_id: str) -> bool:
        """Generate agent profiles and environment config."""
        resp = self.session.post(
            f"{self.base_url}/api/simulation/prepare",
            json={"simulation_id": sim_id},
            timeout=120,
        )
        resp.raise_for_status()
        log.info("Simulation %s preparation started", sim_id)
        return True

    def wait_for_preparation(self, sim_id: str, timeout: int = 300) -> bool:
        """Poll preparation status until ready."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                resp = self.session.get(
                    f"{self.base_url}/api/simulation/prepare/status",
                    params={"simulation_id": sim_id},
                    timeout=10,
                )
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "unknown")
                if status in ("completed", "ready"):
                    return True
                if status == "failed":
                    log.error("Preparation failed for %s", sim_id)
                    return False
            except requests.RequestException as e:
                log.warning("Prep status check failed: %s", e)
            time.sleep(5)
        return False

    def start_simulation(self, sim_id: str) -> bool:
        """Launch the OASIS simulation subprocess."""
        resp = self.session.post(
            f"{self.base_url}/api/simulation/start",
            json={"simulation_id": sim_id},
            timeout=30,
        )
        resp.raise_for_status()
        log.info("Simulation %s started", sim_id)
        return True

    def get_simulation_status(self, sim_id: str) -> str:
        """Poll simulation status. Returns 'running', 'completed', or 'failed'."""
        try:
            resp = self.session.get(
                f"{self.base_url}/api/simulation/status",
                params={"simulation_id": sim_id},
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("status", "unknown")
        except requests.RequestException as e:
            log.warning("Status check failed for %s: %s", sim_id, e)
            return "unknown"

    def stop_simulation(self, sim_id: str) -> bool:
        """Gracefully stop a running simulation."""
        try:
            resp = self.session.post(
                f"{self.base_url}/api/simulation/stop",
                json={"simulation_id": sim_id},
                timeout=15,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException:
            return False

    def wait_for_completion(self, sim_id: str, timeout: int = 600) -> bool:
        """Poll every 10 seconds until simulation completes or times out."""
        deadline = time.monotonic() + timeout
        status = "unknown"
        while time.monotonic() < deadline:
            status = self.get_simulation_status(sim_id)
            if status == "completed":
                log.info("Simulation %s completed", sim_id)
                return True
            if status == "failed":
                log.error("Simulation %s failed", sim_id)
                return False
            log.debug("Simulation %s status: %s (%.0fs remaining)",
                      sim_id, status, deadline - time.monotonic())
            time.sleep(10)
        log.warning("Simulation %s timed out after %ds (last: %s)",
                    sim_id, timeout, status)
        return False

    # ── Report ───────────────────────────────────────────────────────────

    def generate_report(self, sim_id: str) -> dict:
        """Trigger the ReACT-based report agent."""
        resp = self.session.post(
            f"{self.base_url}/api/report/generate",
            json={"simulation_id": sim_id},
            timeout=120,
        )
        resp.raise_for_status()
        return resp.json()

    def get_report(self, sim_id: str) -> dict:
        """Retrieve the generated report. Triggers generation if needed."""
        # Try existing report first
        try:
            resp = self.session.get(
                f"{self.base_url}/api/report/logs",
                params={"simulation_id": sim_id},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("report") or data.get("content"):
                return data
        except requests.RequestException:
            pass

        # Trigger generation
        return self.generate_report(sim_id)

    def chat_with_report(self, sim_id: str, question: str) -> str:
        """Ask the report agent a follow-up question."""
        resp = self.session.post(
            f"{self.base_url}/api/report/chat",
            json={"simulation_id": sim_id, "message": question},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", data.get("message", str(data)))

    # ── Probability Extraction ───────────────────────────────────────────

    def extract_probability(self, report: dict, event_question: str) -> float:
        """Use LLM to extract a 0.0-1.0 probability from a natural language report."""
        report_text = _flatten_report(report)

        prompt = (
            "You are a calibrated probability estimator. "
            "Given the simulation report below, estimate the probability "
            "that the following event occurs.\n\n"
            f"EVENT QUESTION: {event_question}\n\n"
            f"SIMULATION REPORT:\n{report_text[:8000]}\n\n"
            "Respond with ONLY a single decimal number between 0.00 and 1.00. "
            "Nothing else."
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
            return 0.50  # fallback to max uncertainty

        prob = float(match.group(1))
        prob = max(0.01, min(0.99, prob))
        log.info("Extracted probability %.4f for: %s", prob, event_question[:80])
        return prob

    # ── Cost Estimation ──────────────────────────────────────────────────

    def estimate_cost(self, agent_count: int | None = None, rounds: int | None = None) -> float:
        """Rough LLM cost estimate in dollars.

        ~150 tokens per agent per round at gpt-4o-mini pricing
        ($0.15/1M input + $0.60/1M output ~ $0.0001 per agent-round).
        """
        agent_count = agent_count or self.config.mirofish_agent_count
        rounds = rounds or self.config.mirofish_rounds
        return agent_count * rounds * 0.0001


def _flatten_report(report: dict) -> str:
    """Convert a report dict into readable text for the LLM prompt."""
    parts: list[str] = []

    def _walk(obj, prefix: str = "") -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                _walk(val, prefix=f"{prefix}{key}: ")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, prefix=f"{prefix}[{i}] ")
        else:
            parts.append(f"{prefix}{obj}")

    _walk(report)
    return "\n".join(parts)


def run_full_simulation(client: MiroFishClient, seed_text: str, event_question: str,
                        agent_count: int = None, rounds: int = None) -> dict:
    """Convenience: run the complete simulation pipeline and return results."""
    agent_count = agent_count or client.config.mirofish_agent_count
    rounds = rounds or client.config.mirofish_rounds

    sim_id = client.create_simulation(seed_text, agent_count, rounds)

    # Prepare agents
    client.prepare_simulation(sim_id)
    client.wait_for_preparation(sim_id, timeout=300)

    # Run simulation
    client.start_simulation(sim_id)
    completed = client.wait_for_completion(sim_id, timeout=600)

    if not completed:
        return {
            "sim_id": sim_id,
            "status": "timeout",
            "probability": None,
            "report": None,
            "estimated_cost": client.estimate_cost(agent_count, rounds),
        }

    # Get report and extract probability
    report = client.get_report(sim_id)
    probability = client.extract_probability(report, event_question)

    return {
        "sim_id": sim_id,
        "status": "completed",
        "probability": probability,
        "report": report,
        "estimated_cost": client.estimate_cost(agent_count, rounds),
    }
