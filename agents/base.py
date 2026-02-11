"""
Base strategic agent using OpenAI (gpt-4o).
"""

import os
import json
from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass, field

from openai import OpenAI

from engine.turn import Orders


@dataclass
class AgentConfig:
    """Configuration for a strategic agent."""
    faction: str
    doctrine: str
    risk_tolerance: float = 0.5
    air_priority: str = "balanced"
    ground_priority: str = "balanced"
    constraints: list[str] = field(default_factory=list)
    model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096


class StrategicAgent(ABC):
    """Base class for LLM-powered strategic agents."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.faction = config.faction
        self.client = OpenAI()  # Uses OPENAI_API_KEY env var
        self.conversation_history: list[dict] = []
        self.turn_count = 0

    @property
    @abstractmethod
    def system_prompt(self) -> str:
        """Get the system prompt defining this agent's doctrine and role."""
        pass

    @property
    def orders_schema(self) -> dict:
        """JSON schema for structured orders output."""
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "reasoning": {
                    "type": "string",
                    "description": "Brief explanation of strategic reasoning for this turn"
                },
                "missile_strikes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "battery_id": {"type": "string"},
                            "target_id": {"type": "string"},
                            "target_type": {"type": "string", "enum": ["airbase", "sam_site", "radar", "c2", "logistics", "ground_unit"]},
                            "missiles": {"type": "integer"}
                        },
                        "required": ["battery_id", "target_id", "target_type", "missiles"]
                    }
                },
                "ew_missions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "unit_id": {"type": "string"},
                            "mission_type": {"type": "string", "enum": ["jam_radar", "jam_comms", "gps_denial", "cyber", "sigint"]}
                        },
                        "required": ["unit_id", "mission_type"]
                    }
                },
                "air_missions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "squadron_id": {"type": "string"},
                            "mission_type": {"type": "string", "enum": ["cap", "sweep", "escort", "strike", "sead", "cas"]},
                            "target_id": {"type": "string"},
                            "aircraft": {"type": "integer"}
                        },
                        "required": ["squadron_id", "mission_type", "target_id", "aircraft"]
                    }
                },
                "drone_missions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "unit_id": {"type": "string"},
                            "mission_type": {"type": "string", "enum": ["isr", "strike", "sead", "loitering"]},
                            "target_id": {"type": "string"}
                        },
                        "required": ["unit_id", "mission_type", "target_id"]
                    }
                },
                "artillery_missions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "battery_id": {"type": "string"},
                            "target_id": {"type": "string"},
                            "rounds": {"type": "integer"},
                            "mission_type": {"type": "string", "enum": ["bombardment", "suppression", "counter_battery", "smoke"]}
                        },
                        "required": ["battery_id", "target_id", "rounds", "mission_type"]
                    }
                },
                "helicopter_missions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "unit_id": {"type": "string"},
                            "mission_type": {"type": "string", "enum": ["attack", "cas", "air_assault", "scout", "csar"]},
                            "target_id": {"type": "string"},
                            "helicopters": {"type": "integer"}
                        },
                        "required": ["unit_id", "mission_type", "target_id", "helicopters"]
                    }
                },
                "ground_orders": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "unit_id": {"type": "string"},
                            "action": {"type": "string", "enum": ["attack", "defend", "move", "withdraw", "reserve"]},
                            "target_id": {"type": "string"},
                            "posture": {"type": "string", "enum": ["assault", "probe", "exploitation", "defend", "delay"]}
                        },
                        "required": ["unit_id", "action", "target_id", "posture"]
                    }
                },
                "sf_missions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "unit_id": {"type": "string"},
                            "mission_type": {"type": "string", "enum": ["raid", "recon", "sabotage", "da", "sr"]},
                            "target_id": {"type": "string"}
                        },
                        "required": ["unit_id", "mission_type", "target_id"]
                    }
                }
            },
            "required": ["reasoning", "missile_strikes", "ew_missions", "air_missions", "drone_missions", "artillery_missions", "helicopter_missions", "ground_orders", "sf_missions"]
        }

    def generate_orders(self, game_state: dict, previous_reports: list = None) -> Orders:
        """Generate orders for the current turn based on game state."""
        self.turn_count += 1

        # Build the prompt with current situation
        situation_prompt = self._build_situation_prompt(game_state, previous_reports)

        # Add to conversation history
        self.conversation_history.append({
            "role": "user",
            "content": situation_prompt
        })

        # Call GPT-5.2 with structured output
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": self.system_prompt},
                *self.conversation_history
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "military_orders",
                    "schema": self.orders_schema,
                    "strict": True
                }
            },
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )

        # Parse response
        response_text = response.choices[0].message.content
        orders_dict = json.loads(response_text)

        # Add assistant response to history
        self.conversation_history.append({
            "role": "assistant",
            "content": response_text
        })

        # Convert to Orders object
        return self._dict_to_orders(orders_dict)

    def _build_situation_prompt(self, game_state: dict, previous_reports: list = None) -> str:
        """Build situation briefing prompt for the agent."""
        prompt = f"""
## SITUATION REPORT - TURN {game_state['turn']}
Day {game_state['day']}, Time: {game_state['time_of_day'].upper()}
Weather: {game_state['weather']}

### FRIENDLY FORCES (USE EXACT IDs IN ORDERS)
"""
        # Categorize units for clearer presentation
        categories = {
            'aircraft': [],
            'missile': [],
            'air_defense': [],
            'artillery': [],
            'helicopter': [],
            'drone': [],
            'ground': [],
            'special_forces': [],
            'isr': [],
            'other': []
        }

        for unit in game_state.get('own_units', []):
            unit_type = unit.get('type', 'unknown').lower()
            unit_id = unit.get('id', 'unknown')

            # Categorize by type
            if any(x in unit_type for x in ['rafale', 'su30', 'mig', 'mirage', 'f16', 'jf17', 'j10', 'jaguar', 'tejas']):
                categories['aircraft'].append(unit)
            elif any(x in unit_type for x in ['brahmos', 'nirbhay', 'pralay', 'babur', 'raad', 'shaheen', 'ghaznavi']):
                categories['missile'].append(unit)
            elif any(x in unit_type for x in ['s400', 'akash', 'spyder', 'mrsam', 'hq9', 'hq16', 'spada']):
                categories['air_defense'].append(unit)
            elif any(x in unit_type for x in ['pinaka', 'smerch', 'm777', 'dhanush', 'k9', 'a100']):
                categories['artillery'].append(unit)
            elif any(x in unit_type for x in ['apache', 'lch', 'rudra', 'chinook', 'cobra', 't129', 'z10', 'mi17']):
                categories['helicopter'].append(unit)
            elif any(x in unit_type for x in ['heron', 'harop', 'mq9', 'wing_loong', 'burraq', 'shahpar']):
                categories['drone'].append(unit)
            elif any(x in unit_type for x in ['corps', 'division', 'brigade', 'infantry', 'armor', 'mech', 'mountain']):
                categories['ground'].append(unit)
            elif any(x in unit_type for x in ['para_sf', 'marcos', 'garud', 'ssg', 'zarrar']):
                categories['special_forces'].append(unit)
            elif any(x in unit_type for x in ['awacs', 'phalcon', 'netra', 'erieye']):
                categories['isr'].append(unit)
            else:
                categories['other'].append(unit)

        # Print each category with exact IDs
        for cat_name, units in categories.items():
            if units:
                prompt += f"\n**{cat_name.upper()}** ({len(units)} units):\n"
                for u in units:
                    prompt += f"  - ID: `{u['id']}` | Type: {u.get('type', 'N/A')} | Strength: {u.get('strength', 'N/A')} | Status: {u.get('status', 'ready')}\n"

        # Enemy intelligence
        prompt += "\n### ENEMY FORCES (INTELLIGENCE)\n"

        known = game_state.get('known_enemies', [])
        if known:
            prompt += f"**Confirmed contacts**: {len(known)}\n"
            for enemy in known[:10]:
                prompt += f"  - {enemy.get('type', 'Unknown')}: location {enemy.get('location')}, est. strength {enemy.get('estimated_strength', 'unknown')}\n"
        else:
            prompt += "No confirmed enemy contacts.\n"

        suspected = game_state.get('suspected_enemies', [])
        if suspected:
            prompt += f"\n**Suspected contacts**: {len(suspected)}\n"

        # Supply status
        supply = game_state.get('supply_status', {})
        prompt += f"\n### LOGISTICS\n"
        prompt += f"Units undersupplied: {supply.get('units_undersupplied', 0)}\n"
        prompt += f"Effective supply capacity: {supply.get('effective_capacity', 'N/A')}\n"

        # VP status
        vp = game_state.get('vp', {})
        prompt += f"\n### VICTORY POINTS\n"
        prompt += f"India: {vp.get('india', 0)} | Pakistan: {vp.get('pakistan', 0)}\n"

        # Previous turn results
        if previous_reports:
            prompt += "\n### PREVIOUS TURN RESULTS\n"
            for report in previous_reports[-5:]:  # Last 5 reports
                prompt += f"- {report.get('phase', 'unknown')}: {report.get('result', 'unknown')}\n"

        prompt += "\n### ORDERS REQUIRED\n"
        prompt += "Issue orders for all domains: missiles, EW, air, drones, artillery, helicopters, ground, special forces.\n"
        prompt += "Consider: current objectives, enemy disposition, weather, supply status.\n"

        return prompt

    def _dict_to_orders(self, orders_dict: dict) -> Orders:
        """Convert dictionary response to Orders object."""
        return Orders(
            faction=self.faction,
            turn=self.turn_count,
            missile_strikes=orders_dict.get('missile_strikes', []),
            ew_missions=orders_dict.get('ew_missions', []),
            air_missions=orders_dict.get('air_missions', []),
            drone_missions=orders_dict.get('drone_missions', []),
            artillery_missions=orders_dict.get('artillery_missions', []),
            helicopter_missions=orders_dict.get('helicopter_missions', []),
            ground_orders=orders_dict.get('ground_orders', []),
            sf_missions=orders_dict.get('sf_missions', []),
        )

    def get_reasoning(self) -> Optional[str]:
        """Get the last reasoning from the agent."""
        if self.conversation_history:
            last = self.conversation_history[-1]
            if last['role'] == 'assistant':
                try:
                    return json.loads(last['content']).get('reasoning')
                except:
                    return None
        return None

    def reset(self):
        """Reset agent state for a new game."""
        self.conversation_history = []
        self.turn_count = 0
