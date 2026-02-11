"""
Main game runner for India-Pakistan wargame simulation.

Orchestrates the simulation between two LLM agents.
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

# Load API key from .env
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    for line in env_path.read_text().strip().split("\n"):
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ[key.strip()] = value.strip()

from engine import (
    HexMap, UnitManager, LogisticsSystem, FogOfWar,
    TurnManager, GameState, Orders, Faction
)
from agents import IndiaAgent, PakistanAgent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WargameSimulation:
    """Main simulation orchestrator."""

    def __init__(
        self,
        data_path: str = "data",
        scenario: str = "hot_start_4day",
        log_dir: str = "logs",
    ):
        self.data_path = Path(data_path)
        self.scenario_name = scenario
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        # Initialize components
        logger.info("Initializing map...")
        self.hex_map = HexMap(self.data_path)

        logger.info("Initializing unit manager...")
        self.units = UnitManager(self.data_path)

        logger.info("Initializing logistics...")
        self.logistics = LogisticsSystem()

        logger.info("Initializing fog of war...")
        self.fog = FogOfWar()

        logger.info("Initializing turn manager...")
        self.turn_manager = TurnManager(
            self.hex_map,
            self.units,
            self.logistics,
            self.fog,
            self.data_path,
        )

        # Initialize agents
        logger.info("Initializing India agent...")
        self.india_agent = IndiaAgent.create_default()

        logger.info("Initializing Pakistan agent...")
        self.pakistan_agent = PakistanAgent.create_default()

        # Game log
        self.game_log: list[dict] = []
        self.start_time: Optional[datetime] = None

    def initialize(self):
        """Initialize the game."""
        logger.info(f"Loading scenario: {self.scenario_name}")
        self.turn_manager.initialize_game()

        # Load scenario
        scenario_path = self.data_path / "scenarios" / f"{self.scenario_name}.yaml"
        if scenario_path.exists():
            self._load_scenario(scenario_path)

        self.start_time = datetime.now()

        # Log initialization
        self._log_event("game_start", {
            "scenario": self.scenario_name,
            "india_units": len(self.units.get_units_by_faction(Faction.INDIA)),
            "pakistan_units": len(self.units.get_units_by_faction(Faction.PAKISTAN)),
            "map_cells": len(self.hex_map.cells),
        })

        logger.info("Game initialized")
        logger.info(f"  India units: {len(self.units.get_units_by_faction(Faction.INDIA))}")
        logger.info(f"  Pakistan units: {len(self.units.get_units_by_faction(Faction.PAKISTAN))}")

    def _load_scenario(self, path: Path):
        """Load scenario configuration."""
        import yaml
        with open(path) as f:
            scenario = yaml.safe_load(f)

        # Apply scenario settings
        if "scenario" in scenario:
            self.turn_manager.game_state.max_turns = scenario["scenario"].get("duration_turns", 16)

        # TODO: Apply initial deployments from scenario
        logger.info(f"Scenario loaded: {scenario.get('scenario', {}).get('name', 'Unknown')}")

    def run_turn(self) -> dict:
        """Run a single turn of the simulation."""
        turn = self.turn_manager.game_state.turn + 1
        logger.info(f"\n{'='*60}")
        logger.info(f"TURN {turn}")
        logger.info(f"{'='*60}")

        # Get game state for each agent
        india_state = self.turn_manager.get_game_state_for_agent("india")
        pakistan_state = self.turn_manager.get_game_state_for_agent("pakistan")

        # Get previous turn reports
        previous_reports = []
        if self.turn_manager.game_state.turn_history:
            last_turn = self.turn_manager.game_state.turn_history[-1]
            previous_reports = last_turn.combat_reports

        india_reasoning = ""
        pakistan_reasoning = ""

        # India generates orders
        logger.info("India generating orders...")
        try:
            india_orders = self.india_agent.generate_orders(india_state, previous_reports)
            india_reasoning = self.india_agent.get_reasoning() or ""
            logger.info(f"India reasoning: {india_reasoning[:200]}..." if india_reasoning else "No reasoning")
        except Exception as e:
            logger.error(f"India agent error: {e}")
            india_orders = Orders(faction="india", turn=turn)

        # Pakistan generates orders
        logger.info("Pakistan generating orders...")
        try:
            pakistan_orders = self.pakistan_agent.generate_orders(pakistan_state, previous_reports)
            pakistan_reasoning = self.pakistan_agent.get_reasoning() or ""
            logger.info(f"Pakistan reasoning: {pakistan_reasoning[:200]}..." if pakistan_reasoning else "No reasoning")
        except Exception as e:
            logger.error(f"Pakistan agent error: {e}")
            pakistan_orders = Orders(faction="pakistan", turn=turn)

        # Store for replay collector
        self._last_india_orders = india_orders
        self._last_india_reasoning = india_reasoning
        self._last_pakistan_orders = pakistan_orders
        self._last_pakistan_reasoning = pakistan_reasoning

        # Execute turn
        logger.info("Executing turn...")
        turn_state = self.turn_manager.execute_full_turn(india_orders, pakistan_orders)

        # Log results
        turn_log = {
            "turn": turn,
            "day": turn_state.day,
            "time": turn_state.time_of_day.value,
            "weather": turn_state.weather.value,
            "india_orders_summary": self._summarize_orders(india_orders),
            "pakistan_orders_summary": self._summarize_orders(pakistan_orders),
            "india_reasoning": india_reasoning,
            "pakistan_reasoning": pakistan_reasoning,
            "combat_reports": len(turn_state.combat_reports),
            "vp": {
                "india": self.turn_manager.game_state.india_vp,
                "pakistan": self.turn_manager.game_state.pakistan_vp,
            }
        }

        self._log_event("turn_complete", turn_log)

        # Print summary
        logger.info(f"\nTurn {turn} Complete:")
        logger.info(f"  Combat engagements: {len(turn_state.combat_reports)}")
        logger.info(f"  VP - India: {self.turn_manager.game_state.india_vp}, Pakistan: {self.turn_manager.game_state.pakistan_vp}")

        return turn_log

    def _summarize_orders(self, orders: Orders) -> dict:
        """Summarize orders for logging."""
        return {
            "missile_strikes": len(orders.missile_strikes),
            "ew_missions": len(orders.ew_missions),
            "air_missions": len(orders.air_missions),
            "drone_missions": len(orders.drone_missions),
            "artillery_missions": len(orders.artillery_missions),
            "helicopter_missions": len(orders.helicopter_missions),
            "ground_orders": len(orders.ground_orders),
            "sf_missions": len(orders.sf_missions),
        }

    def run_game(self, max_turns: Optional[int] = None) -> dict:
        """Run the full game."""
        self.initialize()

        from replay_export import ReplayCollector
        replay = ReplayCollector(self)
        replay.snapshot_initial_state()

        max_turns = max_turns or self.turn_manager.game_state.max_turns

        while (self.turn_manager.game_state.turn < max_turns and
               not self.turn_manager.game_state.game_over):
            self.run_turn()

            # Snapshot for replay
            turn_state = self.turn_manager.game_state.turn_history[-1]
            replay.snapshot_turn(
                turn_state,
                self._last_india_orders,
                self._last_pakistan_orders,
                self._last_india_reasoning,
                self._last_pakistan_reasoning,
            )

        # Final results
        results = self._compile_results()
        self._log_event("game_end", results)
        self._save_game_log()

        # Generate replay HTML
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        replay_path = replay.generate(self.log_dir / f"replay_{timestamp}.html")
        logger.info(f"Replay file saved to: {replay_path}")

        return results

    def _compile_results(self) -> dict:
        """Compile final game results."""
        game = self.turn_manager.game_state

        # Count surviving forces
        india_forces = self.units.get_combat_effective_units(Faction.INDIA)
        pakistan_forces = self.units.get_combat_effective_units(Faction.PAKISTAN)

        return {
            "turns_played": game.turn,
            "winner": game.winner,
            "final_vp": {
                "india": game.india_vp,
                "pakistan": game.pakistan_vp,
            },
            "surviving_forces": {
                "india": len(india_forces),
                "pakistan": len(pakistan_forces),
            },
            "duration": str(datetime.now() - self.start_time) if self.start_time else None,
        }

    def _log_event(self, event_type: str, data: dict):
        """Log a game event."""
        self.game_log.append({
            "timestamp": datetime.now().isoformat(),
            "event": event_type,
            "data": data,
        })

    def _save_game_log(self):
        """Save game log to file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = self.log_dir / f"game_{timestamp}.json"

        with open(log_path, "w") as f:
            json.dump(self.game_log, f, indent=2, default=str)

        logger.info(f"Game log saved to: {log_path}")


def main():
    """Run a wargame simulation."""
    import argparse

    parser = argparse.ArgumentParser(description="India-Pakistan Wargame Simulation")
    parser.add_argument("--scenario", default="hot_start_4day", help="Scenario name")
    parser.add_argument("--turns", type=int, default=None, help="Max turns (default: scenario defined)")
    parser.add_argument("--data", default="data", help="Data directory path")
    parser.add_argument("--logs", default="logs", help="Log directory path")

    args = parser.parse_args()

    sim = WargameSimulation(
        data_path=args.data,
        scenario=args.scenario,
        log_dir=args.logs,
    )

    results = sim.run_game(max_turns=args.turns)

    print("\n" + "="*60)
    print("FINAL RESULTS")
    print("="*60)
    print(f"Turns played: {results['turns_played']}")
    print(f"Winner: {results['winner']}")
    print(f"Final VP - India: {results['final_vp']['india']}, Pakistan: {results['final_vp']['pakistan']}")
    print(f"Surviving forces - India: {results['surviving_forces']['india']}, Pakistan: {results['surviving_forces']['pakistan']}")
    print(f"Duration: {results['duration']}")


if __name__ == "__main__":
    main()
