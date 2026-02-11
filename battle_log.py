#!/usr/bin/env python3
"""
Live battle log - streams events as they happen.
"""

import os
import time
import sys
from pathlib import Path

# Load .env from project root (same as game.py)
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")
from engine import HexMap, UnitManager, LogisticsSystem, FogOfWar, TurnManager, Faction
from engine.turn import Orders, Phase
from agents import IndiaAgent, PakistanAgent
from agents.base import AgentConfig

# Configuration
MAX_TURNS = 2  # Change this to run more turns

# Time mapping for turns
def get_time_str(turn, phase_idx=0):
    """Get realistic time string for turn/phase."""
    day = ((turn - 1) // 4) + 1
    turn_in_day = (turn - 1) % 4
    base_hours = [6, 12, 18, 0]  # Dawn, Day, Dusk, Night
    hour = base_hours[turn_in_day] + phase_idx
    if hour >= 24:
        hour -= 24
        day += 1
    return f"Day {day}, {hour:02d}:{(phase_idx * 7) % 60:02d}"

def get_time_period(turn):
    """Get time period name."""
    turn_in_day = (turn - 1) % 4
    return ["DAWN", "MIDDAY", "DUSK", "NIGHT"][turn_in_day]

def log(faction, message, time_str=None):
    """Print a battle log entry."""
    prefix = "🇮🇳 INDIA" if faction == "india" else "🇵🇰 PAKISTAN"
    if faction == "system":
        prefix = "⚡ SYSTEM"
    elif faction == "combat":
        prefix = "💥 COMBAT"
    elif faction == "intel":
        prefix = "📡 INTEL"

    time_prefix = f"[{time_str}] " if time_str else ""
    print(f"{time_prefix}{prefix}: {message}")
    sys.stdout.flush()
    time.sleep(0.05)

def log_header(text):
    """Print a header."""
    print(f"\n{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}\n")
    sys.stdout.flush()

def run_turn(turn_mgr, india_agent, pak_agent, units, turn_num):
    """Run a single turn with live logging."""
    time_str = get_time_str(turn_num)
    time_period = get_time_period(turn_num)
    day = ((turn_num - 1) // 4) + 1

    log_header(f"TURN {turn_num} - {time_str} - {time_period}")

    # Get state
    india_state = turn_mgr.get_game_state_for_agent("india")
    pak_state = turn_mgr.get_game_state_for_agent("pakistan")

    # Show intel summary
    india_known = len(india_state.get('known_enemies', []))
    pak_known = len(pak_state.get('known_enemies', []))
    log("intel", f"India tracks {india_known} enemy units | Pakistan tracks {pak_known} enemy units", time_str)

    # Get previous reports for context
    previous_reports = []
    if turn_mgr.game_state.turn_history:
        previous_reports = turn_mgr.game_state.turn_history[-1].combat_reports

    # India planning
    print("\n--- 🇮🇳 INDIA COMMAND ---\n")
    log("system", "New Delhi war room convening...", time_str)
    time.sleep(0.3)

    india_orders = india_agent.generate_orders(india_state, previous_reports)
    india_reasoning = india_agent.get_reasoning()
    log("india", f"{india_reasoning[:250]}..." if india_reasoning else "Orders issued.", time_str)

    # India orders
    print()
    for strike in india_orders.missile_strikes:
        log("india", f"🚀 MISSILE: {strike.get('missiles', 1)}x → {strike.get('target_id')} ({strike.get('target_type')})", time_str)
    for mission in india_orders.air_missions:
        mtype = mission.get('mission_type', mission.get('type', '?')).upper()
        log("india", f"✈️  AIR {mtype}: {mission.get('aircraft', '?')} aircraft → {mission.get('target_id', 'patrol')}", time_str)
    for mission in india_orders.artillery_missions:
        log("india", f"💣 ARTY: {mission.get('rounds', '?')} rounds → {mission.get('target_id')}", time_str)
    for order in india_orders.ground_orders:
        log("india", f"🪖 GROUND: {order.get('unit_id')} → {order.get('action', '?').upper()}", time_str)
    for mission in india_orders.sf_missions:
        log("india", f"🎯 SF: {mission.get('mission_type', '?').upper()} mission", time_str)
    if india_orders.ew_missions:
        log("india", f"📶 EW: {len(india_orders.ew_missions)} jamming operations", time_str)
    if india_orders.drone_missions:
        log("india", f"🛸 DRONE: {len(india_orders.drone_missions)} ISR missions", time_str)

    # Pakistan response
    print("\n--- 🇵🇰 PAKISTAN COMMAND ---\n")
    time.sleep(0.3)
    log("system", "Rawalpindi GHQ responding...", time_str)
    time.sleep(0.3)

    pak_orders = pak_agent.generate_orders(pak_state, previous_reports)
    pak_reasoning = pak_agent.get_reasoning()
    log("pakistan", f"{pak_reasoning[:250]}..." if pak_reasoning else "Orders issued.", time_str)

    print()
    for strike in pak_orders.missile_strikes:
        log("pakistan", f"🚀 MISSILE: {strike.get('missiles', 1)}x → {strike.get('target_id')} ({strike.get('target_type')})", time_str)
    for mission in pak_orders.air_missions:
        mtype = mission.get('mission_type', mission.get('type', '?')).upper()
        log("pakistan", f"✈️  AIR {mtype}: {mission.get('aircraft', '?')} aircraft → {mission.get('target_id', 'patrol')}", time_str)
    for mission in pak_orders.artillery_missions:
        log("pakistan", f"💣 ARTY: {mission.get('rounds', '?')} rounds → {mission.get('target_id')}", time_str)
    for order in pak_orders.ground_orders:
        log("pakistan", f"🪖 GROUND: {order.get('unit_id')} → {order.get('action', '?').upper()}", time_str)
    for mission in pak_orders.sf_missions:
        log("pakistan", f"🎯 SF: {mission.get('mission_type', '?').upper()} mission", time_str)
    if pak_orders.ew_missions:
        log("pakistan", f"📶 EW: {len(pak_orders.ew_missions)} operations", time_str)
    if pak_orders.drone_missions:
        log("pakistan", f"🛸 DRONE: {len(pak_orders.drone_missions)} ISR missions", time_str)

    # Execute
    print("\n--- ⚔️  COMBAT RESOLUTION ---\n")
    time.sleep(0.2)

    turn_state = turn_mgr.execute_full_turn(india_orders, pak_orders)

    # Report results
    for report in turn_state.combat_reports:
        phase = report.get('phase', 'combat').replace('_', ' ').upper()
        attacker = report.get('attacker_id', '?')
        defender = report.get('defender_id', '?')
        result = str(report.get('result', '')).replace('CombatResult.', '')

        att_losses = report.get('attacker_losses', {})
        def_losses = report.get('defender_losses', {})
        damage = report.get('defender_damage', 0)

        # Determine who won for coloring
        if 'VICTORY' in result:
            log("combat", f"{phase}: {attacker} ➜ {defender} = {result}", time_str)
        elif 'DEFEAT' in result:
            log("combat", f"{phase}: {attacker} ➜ {defender} = {result}", time_str)
        else:
            log("combat", f"{phase}: {attacker} ➜ {defender} = {result}", time_str)

        # Losses
        losses = []
        if att_losses.get('aircraft'):
            losses.append(f"Attacker -{att_losses['aircraft']} aircraft")
        if def_losses.get('aircraft'):
            losses.append(f"Defender -{def_losses['aircraft']} aircraft")
        if damage and damage > 0:
            losses.append(f"Damage: {damage:.0f}")
        if losses:
            print(f"         └─ {' | '.join(losses)}")

        time.sleep(0.1)

    # Summary
    india_effective = len([u for u in units.units.values() if u.faction == Faction.INDIA and u.is_combat_effective()])
    pak_effective = len([u for u in units.units.values() if u.faction == Faction.PAKISTAN and u.is_combat_effective()])

    print(f"\n📊 Turn {turn_num} Summary: {len(turn_state.combat_reports)} engagements")
    print(f"   India effective units: {india_effective} | Pakistan: {pak_effective}")
    print(f"   VP: India {turn_mgr.game_state.india_vp} - Pakistan {turn_mgr.game_state.pakistan_vp}")

    return turn_state


# Main
print("Initializing simulation...")
data_path = Path("data")
hex_map = HexMap(data_path)
units = UnitManager(data_path)
units.load_faction_oob(Faction.INDIA)
units.load_faction_oob(Faction.PAKISTAN)
logistics = LogisticsSystem()
fog = FogOfWar()
turn_mgr = TurnManager(hex_map, units, logistics, fog, data_path)
turn_mgr.initialize_game()

india_agent = IndiaAgent(AgentConfig(faction="india", doctrine="offensive", model="gpt-4o"))
pak_agent = PakistanAgent(AgentConfig(faction="pakistan", doctrine="defensive", model="gpt-4o"))

log_header("INDIA-PAKISTAN CONFLICT - OPERATION BEGINS")
print(f"Running {MAX_TURNS} turns...\n")

for turn in range(1, MAX_TURNS + 1):
    run_turn(turn_mgr, india_agent, pak_agent, units, turn)
    if turn < MAX_TURNS:
        print("\n" + "-"*70)
        time.sleep(0.5)

log_header("SIMULATION PAUSED")
print(f"Completed {MAX_TURNS} turns.")
print(f"Final VP: India {turn_mgr.game_state.india_vp} - Pakistan {turn_mgr.game_state.pakistan_vp}")
