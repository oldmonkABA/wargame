#!/usr/bin/env python3
"""
Quick test of the wargame engine with LLM agents.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment
load_dotenv()

# Verify API key
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("ERROR: OPENAI_API_KEY not set")
    exit(1)
print(f"API key loaded: {api_key[:20]}...")

# Test imports
print("\n1. Testing imports...")
try:
    from engine import HexMap, UnitManager, LogisticsSystem, FogOfWar, TurnManager, Faction
    from engine.turn import Orders
    print("   ✓ Engine imports OK")
except Exception as e:
    print(f"   ✗ Engine import failed: {e}")
    exit(1)

try:
    from agents import IndiaAgent, PakistanAgent
    from agents.base import AgentConfig
    print("   ✓ Agent imports OK")
except Exception as e:
    print(f"   ✗ Agent import failed: {e}")
    exit(1)

# Test engine initialization
print("\n2. Initializing engine...")
try:
    data_path = Path("data")
    hex_map = HexMap(data_path)
    print(f"   ✓ Map: {len(hex_map.cells)} hexes")

    units = UnitManager(data_path)
    units.load_faction_oob(Faction.INDIA)
    units.load_faction_oob(Faction.PAKISTAN)
    india_count = len(units.get_units_by_faction(Faction.INDIA))
    pak_count = len(units.get_units_by_faction(Faction.PAKISTAN))
    print(f"   ✓ Units: India={india_count}, Pakistan={pak_count}")

    logistics = LogisticsSystem()
    fog = FogOfWar()
    turn_mgr = TurnManager(hex_map, units, logistics, fog, data_path)
    print("   ✓ Turn manager initialized")
except Exception as e:
    print(f"   ✗ Engine init failed: {e}")
    import traceback
    traceback.print_exc()
    exit(1)

# Test agent initialization
print("\n3. Initializing agents (gpt-4o for testing)...")
try:
    # Use gpt-4o for testing (faster/cheaper)
    india_config = AgentConfig(
        faction="india",
        doctrine="offensive_conventional",
        model="gpt-4o",  # Change to "o1" or "o3" for reasoning
        temperature=0.7,
    )
    india_agent = IndiaAgent(india_config)
    print("   ✓ India agent ready")

    pak_config = AgentConfig(
        faction="pakistan",
        doctrine="defensive_attrition",
        model="gpt-4o",
        temperature=0.7,
    )
    pak_agent = PakistanAgent(pak_config)
    print("   ✓ Pakistan agent ready")
except Exception as e:
    print(f"   ✗ Agent init failed: {e}")
    exit(1)

# Test single turn
print("\n4. Running Turn 1...")
print("   Getting game state for agents...")

turn_mgr.initialize_game()
india_state = turn_mgr.get_game_state_for_agent("india")
pak_state = turn_mgr.get_game_state_for_agent("pakistan")

print(f"   India sees: {len(india_state['own_units'])} own units, {len(india_state['known_enemies'])} known enemies")
print(f"   Pakistan sees: {len(pak_state['own_units'])} own units, {len(pak_state['known_enemies'])} known enemies")

print("\n   Calling India agent (GPT-4o)...")
try:
    india_orders = india_agent.generate_orders(india_state)
    india_reasoning = india_agent.get_reasoning()
    print(f"   ✓ India orders received")
    print(f"   Reasoning: {india_reasoning[:300] if india_reasoning else 'None'}...")
    print(f"   Orders: missiles={len(india_orders.missile_strikes)}, air={len(india_orders.air_missions)}, ground={len(india_orders.ground_orders)}")
except Exception as e:
    print(f"   ✗ India agent failed: {e}")
    import traceback
    traceback.print_exc()
    india_orders = Orders(faction="india", turn=1)

print("\n   Calling Pakistan agent (GPT-4o)...")
try:
    pak_orders = pak_agent.generate_orders(pak_state)
    pak_reasoning = pak_agent.get_reasoning()
    print(f"   ✓ Pakistan orders received")
    print(f"   Reasoning: {pak_reasoning[:300] if pak_reasoning else 'None'}...")
    print(f"   Orders: missiles={len(pak_orders.missile_strikes)}, air={len(pak_orders.air_missions)}, ground={len(pak_orders.ground_orders)}")
except Exception as e:
    print(f"   ✗ Pakistan agent failed: {e}")
    import traceback
    traceback.print_exc()
    pak_orders = Orders(faction="pakistan", turn=1)

print("\n5. Executing turn...")
try:
    turn_state = turn_mgr.execute_full_turn(india_orders, pak_orders)
    print(f"   ✓ Turn {turn_state.turn_number} complete")
    print(f"   Day {turn_state.day}, {turn_state.time_of_day.value}")
    print(f"   Combat reports: {len(turn_state.combat_reports)}")
except Exception as e:
    print(f"   ✗ Turn execution failed: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*50)
print("TEST COMPLETE")
print("="*50)
