#!/usr/bin/env python3
"""Show detailed Turn 1 combat reports."""

import os
os.environ["OPENAI_API_KEY"] = open(".env").read().split("=")[1].strip()

from pathlib import Path
from engine import HexMap, UnitManager, LogisticsSystem, FogOfWar, TurnManager, Faction
from engine.turn import Orders
from agents import IndiaAgent, PakistanAgent
from agents.base import AgentConfig

# Initialize
data_path = Path("data")
hex_map = HexMap(data_path)
units = UnitManager(data_path)
units.load_faction_oob(Faction.INDIA)
units.load_faction_oob(Faction.PAKISTAN)
logistics = LogisticsSystem()
fog = FogOfWar()
turn_mgr = TurnManager(hex_map, units, logistics, fog, data_path)

# Agents
india_agent = IndiaAgent(AgentConfig(faction="india", doctrine="offensive", model="gpt-4o"))
pak_agent = PakistanAgent(AgentConfig(faction="pakistan", doctrine="defensive", model="gpt-4o"))

# Run turn 1
turn_mgr.initialize_game()
india_state = turn_mgr.get_game_state_for_agent("india")
pak_state = turn_mgr.get_game_state_for_agent("pakistan")

print("=" * 70)
print("INDIA AGENT DECISION")
print("=" * 70)
india_orders = india_agent.generate_orders(india_state)
print(f"\nREASONING:\n{india_agent.get_reasoning()}\n")

print("\nORDERS:")
print(f"  Missile strikes: {len(india_orders.missile_strikes)}")
for m in india_orders.missile_strikes:
    print(f"    - {m}")
print(f"  Air missions: {len(india_orders.air_missions)}")
for a in india_orders.air_missions:
    print(f"    - {a}")
print(f"  Artillery: {len(india_orders.artillery_missions)}")
for a in india_orders.artillery_missions:
    print(f"    - {a}")
print(f"  Ground: {len(india_orders.ground_orders)}")
for g in india_orders.ground_orders:
    print(f"    - {g}")
print(f"  SF: {len(india_orders.sf_missions)}")
print(f"  Drones: {len(india_orders.drone_missions)}")
print(f"  EW: {len(india_orders.ew_missions)}")
print(f"  Helicopters: {len(india_orders.helicopter_missions)}")

print("\n" + "=" * 70)
print("PAKISTAN AGENT DECISION")
print("=" * 70)
pak_orders = pak_agent.generate_orders(pak_state)
print(f"\nREASONING:\n{pak_agent.get_reasoning()}\n")

print("\nORDERS:")
print(f"  Missile strikes: {len(pak_orders.missile_strikes)}")
for m in pak_orders.missile_strikes:
    print(f"    - {m}")
print(f"  Air missions: {len(pak_orders.air_missions)}")
for a in pak_orders.air_missions:
    print(f"    - {a}")
print(f"  Artillery: {len(pak_orders.artillery_missions)}")
for a in pak_orders.artillery_missions:
    print(f"    - {a}")
print(f"  Ground: {len(pak_orders.ground_orders)}")
for g in pak_orders.ground_orders:
    print(f"    - {g}")
print(f"  SF: {len(pak_orders.sf_missions)}")
print(f"  Drones: {len(pak_orders.drone_missions)}")
print(f"  EW: {len(pak_orders.ew_missions)}")
print(f"  Helicopters: {len(pak_orders.helicopter_missions)}")

print("\n" + "=" * 70)
print("EXECUTING TURN 1")
print("=" * 70)
turn_state = turn_mgr.execute_full_turn(india_orders, pak_orders)

print(f"\nTurn {turn_state.turn_number} - Day {turn_state.day} - {turn_state.time_of_day.value.upper()}")
print(f"Weather: {turn_state.weather.value}")
print(f"\nCOMBAT REPORTS ({len(turn_state.combat_reports)}):")
print("-" * 70)

for i, report in enumerate(turn_state.combat_reports, 1):
    print(f"\n[{i}] Phase: {report.get('phase', 'unknown').upper()}")
    print(f"    Attacker: {report.get('attacker_id', 'N/A')}")
    print(f"    Defender: {report.get('defender_id', 'N/A')}")
    print(f"    Result: {report.get('result', 'N/A')}")
    if report.get('attacker_losses'):
        print(f"    Attacker losses: {report['attacker_losses']}")
    if report.get('defender_losses'):
        print(f"    Defender losses: {report['defender_losses']}")
    if report.get('defender_damage'):
        print(f"    Defender damage: {report['defender_damage']:.1f}")
    if report.get('notes'):
        for note in report['notes']:
            print(f"    > {note}")

print("\n" + "=" * 70)
print("END OF TURN 1")
print("=" * 70)
