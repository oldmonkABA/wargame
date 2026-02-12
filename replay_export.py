"""
Replay file generator for India-Pakistan wargame simulation.

Produces a self-contained HTML file with Leaflet map visualization,
animated phase-by-phase combat playback, and agent reasoning.
"""

import json
import yaml
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

# Known SAM engagement ranges (km) by type substring
SAM_RANGES_KM = {
    "s400": 380, "s300": 200, "hq9": 125, "hq16": 40, "hq7": 15,
    "akash": 30, "spyder": 18, "mrsam": 70, "barak8": 70, "barak": 70,
    "spada": 25, "crotale": 10, "oerlikon": 5, "zu23": 3, "igla": 5,
    "anza": 5, "fm90": 15, "ly80": 40,
}


def _sam_range(sam_type_str):
    """Infer SAM engagement range from type string."""
    key = (sam_type_str or "").lower().replace("-", "").replace(" ", "")
    for name, rng in SAM_RANGES_KM.items():
        if name in key:
            return rng
    return 50


# Weapons too fast / maneuverable for conventional SAM interception
UNINTERCEPTABLE_WEAPONS = [
    "brahmos", "hypersonic", "zircon", "kinzhal", "df17",
]


def _is_interceptable(unit):
    """Check if a missile unit can be intercepted by SAMs."""
    if unit is None:
        return True
    name = (unit.name or "").lower().replace("-", "").replace(" ", "")
    uid = (unit.id or "").lower().replace("-", "").replace(" ", "")
    utype = (unit.unit_type or "").lower().replace("-", "").replace(" ", "")
    for w in UNINTERCEPTABLE_WEAPONS:
        if w in name or w in uid or w in utype:
            return False
    return True


class ReplayCollector:
    """Collects simulation state each turn and generates an HTML replay file."""

    def __init__(self, sim):
        self.sim = sim
        self.turns = []
        self.static_data = {}

    # ------------------------------------------------------------------
    # Unit position resolution
    # ------------------------------------------------------------------

    def _resolve_unit_position(self, unit, depth=0):
        """Get (lat, lon) for a unit using fallback chain."""
        if depth > 3:
            return None
        loc = unit.location
        if loc.lat is not None and loc.lon is not None:
            return (loc.lat, loc.lon)
        if loc.hex_q is not None and loc.hex_r is not None:
            return self.sim.hex_map.hex_to_latlon(loc.hex_q, loc.hex_r)
        td_loc = unit.type_data.get("location", {})
        if isinstance(td_loc, dict) and td_loc.get("lat") and td_loc.get("lon"):
            return (td_loc["lat"], td_loc["lon"])
        hq_loc = unit.type_data.get("hq_location", {})
        if isinstance(hq_loc, dict) and hq_loc.get("lat") and hq_loc.get("lon"):
            return (hq_loc["lat"], hq_loc["lon"])
        if loc.airbase_id:
            base = self.sim.units.get_airbase(loc.airbase_id)
            if base and base.location.lat is not None:
                return (base.location.lat, base.location.lon)
        if unit.parent_id:
            parent = self.sim.units.get_unit(unit.parent_id)
            if parent:
                return self._resolve_unit_position(parent, depth + 1)
        return None

    def _resolve_origin_position(self, unit):
        """Get origin position for attack animations (airbase for aircraft)."""
        if hasattr(unit, 'base_id') and unit.base_id:
            base = self.sim.units.get_airbase(unit.base_id)
            if base and base.location.lat is not None:
                return (base.location.lat, base.location.lon)
        if unit.location.airbase_id:
            base = self.sim.units.get_airbase(unit.location.airbase_id)
            if base and base.location.lat is not None:
                return (base.location.lat, base.location.lon)
        return self._resolve_unit_position(unit)

    # ------------------------------------------------------------------
    # Snapshot helpers
    # ------------------------------------------------------------------

    def _snapshot_units(self):
        units = []
        for uid, unit in self.sim.units.units.items():
            pos = self._resolve_unit_position(unit)
            if pos is None:
                continue
            strength_pct = round(
                unit.state.strength_current / max(1, unit.state.strength_max) * 100
            )
            units.append({
                "id": unit.id, "name": unit.name,
                "faction": unit.faction.value,
                "category": unit.category.value,
                "type": unit.unit_type,
                "lat": round(pos[0], 4), "lon": round(pos[1], 4),
                "status": unit.status.value,
                "strength": strength_pct,
                "posture": unit.posture.value,
            })
        return units

    def _collect_static_data(self):
        hm = self.sim.hex_map
        rivers = []
        for r in hm.rivers:
            path = [{"lat": p["lat"], "lon": p["lon"]} for p in r.get("path", [])]
            if len(path) >= 2:
                rivers.append({"name": r.get("name", ""), "path": path,
                               "width": r.get("width_avg_m", 100)})
        cities = []
        for c in hm.cities:
            if c.get("lat") and c.get("lon"):
                cities.append({"name": c.get("name", ""), "lat": c["lat"], "lon": c["lon"],
                               "faction": c.get("faction", "neutral"),
                               "population": c.get("population", 0),
                               "type": c.get("type", "minor")})
        airbases = []
        for bid, base in self.sim.units.airbases.items():
            if base.location.lat is not None:
                airbases.append({"id": bid, "name": base.name,
                                 "faction": base.faction.value,
                                 "lat": base.location.lat, "lon": base.location.lon})
        sectors = []
        for s in hm.sectors:
            b = s.get("bounds", {})
            if b.get("north"):
                sectors.append({"id": s.get("id", ""), "name": s.get("name", ""),
                                "terrain": s.get("terrain_primary", "plains"),
                                "north": b["north"], "south": b["south"],
                                "east": b["east"], "west": b["west"]})
        loc_path = [{"lat": p["lat"], "lon": p["lon"]} for p in hm.loc_path]
        choke_points = [{"name": cp.get("name", ""), "lat": cp["lat"], "lon": cp["lon"],
                         "type": cp.get("type", "")}
                        for cp in hm.choke_points if cp.get("lat")]
        self.static_data = {
            "rivers": rivers, "cities": cities, "airbases": airbases,
            "sectors": sectors, "loc_path": loc_path,
            "choke_points": choke_points, "sam_sites": self._load_sam_sites(),
        }

    def _load_sam_sites(self):
        sam_sites = []
        for faction in ["india", "pakistan"]:
            ad_path = self.sim.data_path / faction / "air_defense.yaml"
            if not ad_path.exists():
                continue
            try:
                with open(ad_path) as f:
                    data = yaml.safe_load(f)
            except Exception:
                continue
            sites = (data.get("sam_sites") or data.get("air_defense_systems")
                     or data.get("systems") or [])
            for site in sites:
                loc = site.get("location", {})
                if not isinstance(loc, dict) or not loc.get("lat"):
                    continue
                sam_type = site.get("sam_type", site.get("type", "sam"))
                sam_sites.append({"name": site.get("name", ""), "faction": faction,
                                  "type": str(sam_type), "lat": loc["lat"], "lon": loc["lon"],
                                  "range_km": _sam_range(str(sam_type))})
        return sam_sites

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot_initial_state(self):
        self._collect_static_data()
        self.turns.append({
            "turn": 0, "day": 1, "time": "pre-war",
            "weather": self.sim.hex_map.weather.weather.value,
            "india_vp": 0, "pakistan_vp": 0,
            "units": self._snapshot_units(),
            "combat_events": [],
            "india_orders": {}, "pakistan_orders": {},
            "india_reasoning": "", "pakistan_reasoning": "",
        })

    def snapshot_turn(self, turn_state, india_orders, pakistan_orders,
                      india_reasoning, pakistan_reasoning):
        events = []
        for report in turn_state.combat_reports:
            r = report if isinstance(report, dict) else report.__dict__

            # Resolve target/event location
            to_lat, to_lon = None, None
            loc = r.get("location")
            if loc and isinstance(loc, (list, tuple)) and len(loc) == 2:
                try:
                    to_lat, to_lon = self.sim.hex_map.hex_to_latlon(int(loc[0]), int(loc[1]))
                except Exception:
                    pass
            if to_lat is None:
                defender = self.sim.units.get_unit(r.get("defender_id", ""))
                if defender:
                    pos = self._resolve_unit_position(defender)
                    if pos:
                        to_lat, to_lon = pos
            if to_lat is None:
                attacker = self.sim.units.get_unit(r.get("attacker_id", ""))
                if attacker:
                    pos = self._resolve_unit_position(attacker)
                    if pos:
                        to_lat, to_lon = pos

            # Resolve attacker origin (for flight path animation)
            from_lat, from_lon = None, None
            attacker_unit = self.sim.units.get_unit(r.get("attacker_id", ""))
            if attacker_unit:
                pos = self._resolve_origin_position(attacker_unit)
                if pos:
                    from_lat, from_lon = pos

            result_val = r.get("result", "unknown")
            if hasattr(result_val, "value"):
                result_val = result_val.value

            events.append({
                "phase": r.get("phase", "unknown"),
                "attacker": r.get("attacker_id", ""),
                "defender": r.get("defender_id", ""),
                "attacker_faction": attacker_unit.faction.value if attacker_unit else None,
                "interceptable": _is_interceptable(attacker_unit),
                "result": str(result_val),
                "lat": round(to_lat, 4) if to_lat else None,
                "lon": round(to_lon, 4) if to_lon else None,
                "from_lat": round(from_lat, 4) if from_lat else None,
                "from_lon": round(from_lon, 4) if from_lon else None,
                "attacker_losses": r.get("attacker_losses", {}),
                "defender_losses": r.get("defender_losses", {}),
                "notes": r.get("notes", []),
            })

        def _order_summary(orders):
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

        self.turns.append({
            "turn": turn_state.turn_number, "day": turn_state.day,
            "time": turn_state.time_of_day.value,
            "weather": turn_state.weather.value,
            "india_vp": self.sim.turn_manager.game_state.india_vp,
            "pakistan_vp": self.sim.turn_manager.game_state.pakistan_vp,
            "units": self._snapshot_units(),
            "combat_events": events,
            "india_orders": _order_summary(india_orders),
            "pakistan_orders": _order_summary(pakistan_orders),
            "india_reasoning": india_reasoning or "",
            "pakistan_reasoning": pakistan_reasoning or "",
        })

    def generate(self, output_path):
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        replay_data = {
            "scenario": self.sim.scenario_name,
            "generated": datetime.now().isoformat(),
            "max_turns": self.sim.turn_manager.game_state.max_turns,
            "static": self.static_data,
            "turns": self.turns,
        }
        json_str = json.dumps(replay_data, default=str).replace("</", "<\\/")
        html = HTML_TEMPLATE.replace("/*__REPLAY_DATA__*/", json_str)
        output_path.write_text(html, encoding="utf-8")
        logger.info(f"Replay: {output_path} ({output_path.stat().st_size // 1024} KB)")
        return output_path


# ======================================================================
# Self-contained HTML template with animated combat replay
# ======================================================================

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wargame Replay</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700;800&display=swap">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
      integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'JetBrains Mono','Courier New','Consolas',monospace;background:#0a0a1a;color:#d0d0d0;overflow:hidden;height:100vh}

/* Header */
#header{position:fixed;top:0;left:0;right:0;z-index:1000;height:48px;background:#0f1729;border-bottom:1px solid #1e3a5f;display:flex;align-items:center;padding:0 16px;gap:10px}
.title{font-size:13px;font-weight:700;letter-spacing:2px;color:#7eb8da;text-transform:uppercase;white-space:nowrap}
.controls{display:flex;align-items:center;gap:5px}
.controls button{background:#1a2744;border:1px solid #2a4a6f;color:#7eb8da;width:30px;height:26px;cursor:pointer;border-radius:3px;font-size:12px;display:flex;align-items:center;justify-content:center}
.controls button:hover{background:#243654}
.controls button.active{background:#2a5a3f;border-color:#4CAF50}
#turn-slider{width:160px;accent-color:#2196F3;cursor:pointer}
#turn-num{font-size:12px;font-weight:600;color:#8899aa;min-width:50px;text-align:center}
#speed-select{background:#1a2744;border:1px solid #2a4a6f;color:#7eb8da;font-size:11px;padding:2px 4px;border-radius:3px;cursor:pointer}
.info{margin-left:auto;font-size:11px;color:#778;display:flex;gap:8px;align-items:center}
.info-pill{background:#1a2744;padding:2px 8px;border-radius:10px;border:1px solid #1e3a5f}

/* Phase overlay */
#phase-overlay{position:fixed;top:58px;left:50%;transform:translateX(-50%);z-index:1001;pointer-events:none;
  background:rgba(12,20,35,.92);padding:6px 24px;border:1px solid #2a4a6f;border-radius:4px;
  font-size:12px;font-weight:700;letter-spacing:3px;text-transform:uppercase;display:none;
  transition:opacity .3s}

/* Feed reasoning block */
.feed-reasoning{font-size:11px;color:#8899aa;line-height:1.4;white-space:pre-wrap;word-break:break-word;
  padding:6px 8px;margin:4px 0;background:rgba(10,21,32,.5);border-radius:3px;border-left:2px solid rgba(255,255,255,.1);
  max-height:120px;overflow-y:auto}
.feed-reasoning::-webkit-scrollbar{width:3px}
.feed-reasoning::-webkit-scrollbar-thumb{background:rgba(255,255,255,.1);border-radius:2px}
.feed-reasoning-toggle{font-size:10px;color:#556;cursor:pointer;padding:2px 0;letter-spacing:1px}
.feed-reasoning-toggle:hover{color:#88a}

/* Header VP compact */
.vp-header{display:flex;align-items:center;gap:10px;margin-left:8px}
.vp-h{font-size:11px;font-weight:700;display:flex;align-items:center;gap:4px}
.vp-h.india{color:#2196F3}.vp-h.pakistan{color:#4CAF50}
.vp-bar-sm{width:60px;height:4px;background:#1a2d45;border-radius:2px;overflow:hidden;display:inline-block}
.vp-fill-sm{height:100%;border-radius:2px;transition:width .3s}
.vp-fill-sm.india{background:#2196F3}.vp-fill-sm.pakistan{background:#4CAF50}

/* Map (full screen behind feeds) */
#map{position:fixed;top:48px;left:0;right:0;bottom:0}

/* Battle Feed — transparent left/right sidebars over map */
.feed-col{position:fixed;top:48px;bottom:0;width:280px;z-index:999;
  background:rgba(6,10,18,.45);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);
  font-family:'JetBrains Mono','Courier New','Consolas','Liberation Mono',monospace;font-size:12px;line-height:1.5;
  overflow-y:auto;padding:6px 12px;scroll-behavior:smooth}
.feed-col::-webkit-scrollbar{width:4px}
.feed-col::-webkit-scrollbar-track{background:transparent}
.feed-col::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:3px}
#feed-pakistan{left:0;border-right:1px solid rgba(76,175,80,.25)}
#feed-india{right:0;border-left:1px solid rgba(33,150,243,.25)}
.feed-col-label{font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;
  padding:2px 0 4px 0;opacity:.5;text-align:center}
.feed-col-label.pakistan{color:#4CAF50}.feed-col-label.india{color:#2196F3}
.feed-line{padding:1px 0;opacity:0;animation:feedIn .15s ease-out forwards;white-space:pre-wrap;word-break:break-word}
@keyframes feedIn{0%{opacity:0;transform:translateX(-8px)}100%{opacity:1;transform:translateX(0)}}
.feed-tag{float:right;font-size:9px;font-weight:700;letter-spacing:1px;opacity:.4}
.feed-phase{padding:4px 0 2px 0;font-weight:700;letter-spacing:2px;font-size:11px;
  border-bottom:1px solid rgba(255,255,255,.06);margin-top:4px}
.feed-sep{border-top:1px solid rgba(255,255,255,.04);margin:3px 0;height:0}
.feed-cursor{display:inline-block;width:6px;height:12px;margin-left:2px;
  animation:fblink 1s step-end infinite;vertical-align:middle}
#feed-pakistan .feed-cursor{background:#4CAF50}
#feed-india .feed-cursor{background:#2196F3}
@keyframes fblink{0%,100%{opacity:1}50%{opacity:0}}
/* Feed colors */
.fc-red{color:#ff4444}.fc-green{color:#44ee44}.fc-amber{color:#ffaa22}
.fc-cyan{color:#44ddff}.fc-white{color:#ccddee}.fc-orange{color:#ff8844}
.fc-purple{color:#cc88ff}.fc-teal{color:#66ccaa}.fc-yellow{color:#ffcc00}
.fc-dim{color:#556677}
.leaflet-container{background:#0a0a1a}
.leaflet-control-layers{background:#111d2e!important;color:#aab!important;border:1px solid #1a2d45!important;font-size:11px}
.leaflet-control-layers label{color:#99a}
.leaflet-control-zoom a{background:#111d2e!important;color:#7eb8da!important;border-color:#1a2d45!important}
.leaflet-tooltip{background:#111d2e;color:#ccd;border:1px solid #2a4a6f;font-size:11px;padding:4px 8px;border-radius:3px;box-shadow:0 2px 8px rgba(0,0,0,.5)}
.leaflet-tooltip-top:before{border-top-color:#2a4a6f}.leaflet-tooltip-bottom:before{border-bottom-color:#2a4a6f}
.leaflet-tile-pane{filter:brightness(.6) invert(1) contrast(3) hue-rotate(200deg) saturate(.3) brightness(.7)}

/* Icons */
.unit-icon,.airbase-icon,.combat-pulse,.anim-icon{background:transparent!important;border:none!important}
.combat-dot{width:14px;height:14px;background:rgba(255,68,68,.6);border:2px solid #ff4444;border-radius:50%;animation:cpulse 1.5s ease-out infinite}
@keyframes cpulse{0%{box-shadow:0 0 0 0 rgba(255,68,68,.5)}70%{box-shadow:0 0 0 12px rgba(255,68,68,0)}100%{box-shadow:0 0 0 0 rgba(255,68,68,0)}}

/* Explosion — big, multi-stage */
.boom-wrap{position:relative;width:80px;height:80px}
.boom-core{position:absolute;inset:15px;border-radius:50%;
  background:radial-gradient(circle,#fff 0%,rgba(255,220,0,1) 20%,rgba(255,120,0,.9) 45%,rgba(255,0,0,.4) 70%,transparent 100%);
  animation:boomCore 1.1s ease-out forwards}
.boom-ring{position:absolute;inset:0;border-radius:50%;border:2px solid rgba(255,200,0,.7);
  animation:boomRing 1s ease-out forwards}
.boom-smoke{position:absolute;inset:-10px;border-radius:50%;
  background:radial-gradient(circle,rgba(80,60,40,.5) 0%,rgba(40,30,20,.2) 50%,transparent 80%);
  animation:boomSmoke 1.5s ease-out forwards}
@keyframes boomCore{0%{transform:scale(0);opacity:1}30%{transform:scale(1.2);opacity:1}60%{transform:scale(1);opacity:.7}100%{transform:scale(.5);opacity:0}}
@keyframes boomRing{0%{transform:scale(0);opacity:1;border-width:3px}100%{transform:scale(3);opacity:0;border-width:1px}}
@keyframes boomSmoke{0%{transform:scale(0);opacity:0}30%{transform:scale(.5);opacity:.6}100%{transform:scale(2.5);opacity:0}}

/* Small explosion */
.boom-sm{width:36px;height:36px;border-radius:50%;
  background:radial-gradient(circle,#fff 0%,rgba(255,180,0,.9) 30%,rgba(255,100,0,.5) 60%,transparent 100%);
  animation:boomSm .7s ease-out forwards}
@keyframes boomSm{0%{transform:scale(0);opacity:1}40%{transform:scale(1.1);opacity:.9}100%{transform:scale(1.5);opacity:0}}

/* Ground flash */
.ground-flash-wrap{position:relative;width:60px;height:60px}
.ground-flash-ring{position:absolute;inset:0;border-radius:50%;border:3px solid rgba(255,200,0,.8);
  animation:gflash 1s ease-out forwards}
.ground-flash-core{position:absolute;inset:15px;border-radius:50%;
  background:radial-gradient(circle,rgba(255,200,0,.9) 0%,rgba(255,120,0,.5) 60%,transparent 100%);
  animation:gcore .8s ease-out forwards}
@keyframes gflash{0%{transform:scale(0);opacity:1;border-width:3px}50%{transform:scale(1);opacity:.8}100%{transform:scale(2.5);opacity:0;border-width:1px}}
@keyframes gcore{0%{transform:scale(0);opacity:1}30%{transform:scale(1);opacity:.8}100%{transform:scale(.3);opacity:0}}

/* SAM interception */
.intercept-wrap{position:relative;width:60px;height:60px}
.intercept-core{position:absolute;inset:10px;border-radius:50%;
  background:radial-gradient(circle,#fff 0%,rgba(100,200,255,1) 30%,rgba(50,150,255,.6) 60%,transparent 100%);
  animation:boomCore .8s ease-out forwards}
.intercept-ring{position:absolute;inset:0;border-radius:50%;border:2px solid rgba(100,200,255,.7);
  animation:boomRing .8s ease-out forwards}
.sam-miss-flash{width:24px;height:24px;border-radius:50%;
  background:radial-gradient(circle,rgba(200,200,255,.7) 0%,rgba(100,150,255,.3) 60%,transparent 100%);
  animation:boomSm .5s ease-out forwards}

/* Missile exhaust */
.missile-exhaust{position:absolute;left:-8px;top:50%;transform:translateY(-50%);
  width:12px;height:6px;border-radius:0 50% 50% 0;
  background:linear-gradient(90deg,transparent 0%,rgba(255,160,0,.9) 40%,rgba(255,255,200,1) 100%);
  animation:exhaust .15s ease-in-out infinite alternate;filter:blur(0.5px)}
@keyframes exhaust{0%{width:8px;opacity:.7}100%{width:14px;opacity:1}}

/* Engagement labels */
.engage-label{font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;
  white-space:nowrap;text-align:center;color:#ccddee;
  text-shadow:0 0 8px #000,0 0 16px #000,0 1px 3px rgba(0,0,0,.9);
  animation:labelIn .4s ease-out forwards}
.kill-label{font-size:14px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;
  white-space:nowrap;text-align:center;color:#ff4444;
  text-shadow:0 0 12px rgba(255,0,0,.7),0 0 24px rgba(255,0,0,.4),0 1px 3px rgba(0,0,0,.9);
  animation:killIn .6s ease-out forwards}
.intercept-label{font-size:14px;font-weight:800;letter-spacing:1.5px;text-transform:uppercase;
  white-space:nowrap;text-align:center;color:#44aaff;
  text-shadow:0 0 12px rgba(0,150,255,.7),0 0 24px rgba(0,150,255,.4),0 1px 3px rgba(0,0,0,.9);
  animation:killIn .6s ease-out forwards}
@keyframes labelIn{0%{opacity:0;transform:translateY(8px)}100%{opacity:1;transform:translateY(0)}}
@keyframes killIn{0%{opacity:0;transform:scale(.5)}50%{opacity:1;transform:scale(1.2)}100%{opacity:1;transform:scale(1)}}

/* Drone swarm particles */
.drone-swarm-wrap{position:relative;width:60px;height:60px}
.drone-dot{position:absolute;width:4px;height:4px;border-radius:50%;background:#aa66ff;
  box-shadow:0 0 4px #aa66ff,0 0 8px rgba(170,102,255,.5);
  animation:swarmBuzz .6s ease-in-out infinite alternate}
.drone-dot:nth-child(2){animation-delay:.1s}.drone-dot:nth-child(3){animation-delay:.2s}
.drone-dot:nth-child(4){animation-delay:.15s}.drone-dot:nth-child(5){animation-delay:.25s}
.drone-dot:nth-child(6){animation-delay:.05s}.drone-dot:nth-child(7){animation-delay:.3s}
.drone-dot:nth-child(8){animation-delay:.12s}
@keyframes swarmBuzz{0%{transform:translate(0,0)}100%{transform:translate(3px,2px)}}
.drone-strike-flash{width:30px;height:30px;border-radius:50%;
  background:radial-gradient(circle,#fff 0%,rgba(170,102,255,.9) 30%,rgba(130,60,220,.4) 60%,transparent 100%);
  animation:droneFlash .6s ease-out forwards}
@keyframes droneFlash{0%{transform:scale(0);opacity:1}40%{transform:scale(1.2);opacity:.9}100%{transform:scale(1.8);opacity:0}}
.drone-label{font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;
  white-space:nowrap;text-align:center;color:#cc99ff;
  text-shadow:0 0 8px rgba(130,60,220,.7),0 0 16px rgba(130,60,220,.4),0 1px 3px rgba(0,0,0,.9);
  animation:labelIn .4s ease-out forwards}

/* Helicopter animations */
.heli-rotor-wrap{position:relative;width:40px;height:40px}
.heli-body{position:absolute;inset:10px;font-size:18px;text-align:center;line-height:20px}
.heli-rotor{position:absolute;top:2px;left:50%;width:36px;height:2px;margin-left:-18px;
  background:rgba(102,204,170,.6);border-radius:1px;animation:rotorSpin .15s linear infinite}
@keyframes rotorSpin{0%{transform:rotate(0)}100%{transform:rotate(180deg)}}
.heli-strafe-flash{width:24px;height:24px;border-radius:50%;
  background:radial-gradient(circle,#fff 0%,rgba(102,204,170,.8) 40%,rgba(60,180,140,.3) 70%,transparent 100%);
  animation:heliFlash .5s ease-out forwards}
@keyframes heliFlash{0%{transform:scale(0);opacity:1}50%{transform:scale(1);opacity:.8}100%{transform:scale(1.5);opacity:0}}
.heli-label{font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;
  white-space:nowrap;text-align:center;color:#66ccaa;
  text-shadow:0 0 8px rgba(60,180,140,.7),0 0 16px rgba(60,180,140,.4),0 1px 3px rgba(0,0,0,.9);
  animation:labelIn .4s ease-out forwards}

/* SF operations */
.sf-ping-wrap{position:relative;width:50px;height:50px}
.sf-ping-ring{position:absolute;inset:0;border-radius:50%;border:2px solid rgba(204,136,255,.7);
  animation:sfPing 1.2s ease-out forwards}
.sf-ping-core{position:absolute;inset:18px;border-radius:50%;
  background:radial-gradient(circle,rgba(204,136,255,.9) 0%,rgba(160,80,220,.4) 60%,transparent 100%);
  animation:sfCore .8s ease-out forwards}
@keyframes sfPing{0%{transform:scale(0);opacity:1;border-width:2px}60%{opacity:.7}100%{transform:scale(2.5);opacity:0;border-width:1px}}
@keyframes sfCore{0%{transform:scale(0);opacity:1}40%{transform:scale(1.2);opacity:.8}100%{transform:scale(0);opacity:0}}
.sf-label{font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
  white-space:nowrap;text-align:center;color:#cc88ff;
  text-shadow:0 0 8px rgba(160,80,220,.7),0 0 16px rgba(160,80,220,.4),0 1px 3px rgba(0,0,0,.9);
  animation:sfFadeIn .6s ease-out forwards}
@keyframes sfFadeIn{0%{opacity:0;transform:translateY(6px)}100%{opacity:1;transform:translateY(0)}}

/* Floating combat text (rises and fades) */
.float-text{font-size:13px;font-weight:800;letter-spacing:1px;text-transform:uppercase;
  white-space:nowrap;text-align:center;
  text-shadow:0 0 10px rgba(0,0,0,.9),0 0 20px rgba(0,0,0,.7),0 1px 3px rgba(0,0,0,.9);
  animation:floatUp 3.2s ease-out forwards;pointer-events:none}
.float-text.ft-large{font-size:16px;letter-spacing:1.5px}
.float-text.ft-small{font-size:11px;font-weight:700}
.float-text.ft-red{color:#ff4444}.float-text.ft-green{color:#44ee44}.float-text.ft-amber{color:#ffaa22}
.float-text.ft-cyan{color:#44ddff}.float-text.ft-orange{color:#ff8844}.float-text.ft-purple{color:#cc88ff}.float-text.ft-teal{color:#66ccaa}
@keyframes floatUp{0%{opacity:1;transform:translateY(0)}50%{opacity:.95}80%{opacity:.5}100%{opacity:0;transform:translateY(-50px)}}

/* CRT scanline overlay */
#crt-overlay{position:fixed;inset:0;pointer-events:none;z-index:2000;mix-blend-mode:overlay;
  background:repeating-linear-gradient(0deg,rgba(0,0,0,.15) 0px,rgba(0,0,0,.15) 1px,transparent 1px,transparent 3px);
  display:none}
#crt-overlay.active{display:block}

/* Screen shake */
.shaking{animation:shake .4s ease-out}
</style>
</head>
<body>

<div id="header">
  <div class="title">India-Pakistan Wargame</div>
  <div class="controls">
    <button onclick="manualPrev()" title="Previous turn">&#9664;</button>
    <span id="turn-num">0/16</span>
    <button onclick="manualNext()" title="Next turn">&#9654;</button>
    <input type="range" id="turn-slider" min="0" value="0" oninput="manualGo(+this.value)">
    <button id="play-btn" onclick="togglePlay()" title="Animated playback (Space)">&#9654;</button>
    <select id="speed-select" onchange="animSpeed=+this.value" title="Animation speed">
      <option value="0.5">0.5x</option>
      <option value="1" selected>1x</option>
      <option value="2">2x</option>
      <option value="3">3x</option>
    </select>
    <button id="sound-btn" onclick="toggleSound()" title="Toggle sound">&#128264;</button>
    <button id="crt-btn" onclick="toggleCRT()" title="Toggle CRT effect">CRT</button>
  </div>
  <div class="vp-header">
    <span class="vp-h india">IND <div class="vp-bar-sm"><div class="vp-fill-sm india" id="vp-india-bar" style="width:50%"></div></div> <span id="india-vp">0</span></span>
    <span class="vp-h pakistan">PAK <div class="vp-bar-sm"><div class="vp-fill-sm pakistan" id="vp-pak-bar" style="width:50%"></div></div> <span id="pakistan-vp">0</span></span>
  </div>
  <div class="info">
    <span class="info-pill" id="day-display">Day 1 Pre-war</span>
    <span class="info-pill" id="weather-display">Clear</span>
  </div>
</div>

<div id="phase-overlay"></div>

<div id="map"></div>
<div id="crt-overlay"></div>

<div class="feed-col" id="feed-pakistan"><div class="feed-col-label pakistan">Pakistan</div><span class="feed-cursor"></span></div>
<div class="feed-col" id="feed-india"><div class="feed-col-label india">India</div><span class="feed-cursor"></span></div>

<script>
var D = /*__REPLAY_DATA__*/;
var turn = 0, playing = false, animSpeed = 1;
var map, unitLy, combatLy, samLy, riverLy, cityLy, airbaseLy, locLy, sectorLy, animLy;
var currentAnim = null;
var catSize = {ground:10,aircraft:7,missile:6,air_defense:6,artillery:7,helicopter:6,drone:5,special_forces:5,isr:5};

// ── Phase config ──
var PHASE_DEFS = [
  {match:/^missile/,  label:'MISSILE STRIKES',  color:'#ff4444', type:'missile'},
  {match:/^air/,      label:'AIR OPERATIONS',   color:'#4499ff', type:'air'},
  {match:/^drone/,    label:'DRONE OPS',        color:'#aa66ff', type:'drone'},
  {match:/^artiller/, label:'ARTILLERY FIRE',   color:'#ff8844', type:'arty'},
  {match:/^heli/,     label:'HELICOPTER OPS',   color:'#66ccaa', type:'heli'},
  {match:/^ground/,   label:'GROUND COMBAT',    color:'#ffcc00', type:'ground'},
  {match:/^special/,  label:'SPECIAL FORCES',   color:'#cc88ff', type:'sf'},
  {match:/./,         label:'COMBAT',           color:'#aaaaaa', type:'ground'}
];

function phaseFor(e) {
  for (var i = 0; i < PHASE_DEFS.length; i++) {
    if (PHASE_DEFS[i].match.test(e.phase)) return PHASE_DEFS[i];
  }
  return PHASE_DEFS[PHASE_DEFS.length - 1];
}

// ── Init ──
function init() {
  map = L.map('map', {zoomControl:true}).setView([30.25,72.0],6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
    attribution:'&copy; OpenStreetMap',maxZoom:12,minZoom:4}).addTo(map);

  unitLy = L.layerGroup().addTo(map);
  combatLy = L.layerGroup().addTo(map);
  animLy = L.layerGroup().addTo(map);
  samLy = L.layerGroup().addTo(map);
  riverLy = L.layerGroup().addTo(map);
  cityLy = L.layerGroup().addTo(map);
  airbaseLy = L.layerGroup().addTo(map);
  locLy = L.layerGroup().addTo(map);
  sectorLy = L.layerGroup();

  L.control.layers(null,{
    'Units':unitLy,'SAM Coverage':samLy,'Combat Events':combatLy,
    'Animations':animLy,'Rivers':riverLy,'Cities':cityLy,
    'Airbases':airbaseLy,'LOC / Border':locLy,'Sectors':sectorLy
  },{position:'topright',collapsed:true}).addTo(map);

  drawStatic();
  feedInit();
  document.getElementById('turn-slider').max = D.turns.length - 1;
  showTurn(0);
  feedTurnSummary(D.turns[0]);
}

// ── Static layers ──
function drawStatic() {
  var s = D.static;
  (s.rivers||[]).forEach(function(r){
    if(!r.path||r.path.length<2)return;
    L.polyline(r.path.map(function(p){return[p.lat,p.lon]}),{
      color:'#4488cc',weight:r.width>200?3:2,opacity:.6}).bindTooltip(r.name).addTo(riverLy);
  });
  (s.cities||[]).forEach(function(c){
    if(!c.lat)return;
    var cl=c.faction==='india'?'#5599dd':c.faction==='pakistan'?'#55aa77':'#888';
    var rd=c.type==='capital'?7:c.type==='major'?5:3;
    L.circleMarker([c.lat,c.lon],{radius:rd,color:cl,fillColor:cl,fillOpacity:.5,weight:1})
     .bindTooltip(c.name+(c.population>0?' ('+(c.population/1e6).toFixed(1)+'M)':'')).addTo(cityLy);
  });
  (s.airbases||[]).forEach(function(ab){
    if(!ab.lat)return;
    var cl=ab.faction==='india'?'#5599dd':'#55aa77';
    L.marker([ab.lat,ab.lon],{icon:L.divIcon({className:'airbase-icon',
      html:'<div style="color:'+cl+';font-size:16px;text-align:center">&#9992;</div>',
      iconSize:[20,20],iconAnchor:[10,10]})}).bindTooltip(ab.name).addTo(airbaseLy);
  });
  if(s.loc_path&&s.loc_path.length>=2){
    L.polyline(s.loc_path.map(function(p){return[p.lat,p.lon]}),{
      color:'#cc4444',weight:2,dashArray:'8,5',opacity:.7}).bindTooltip('Line of Control').addTo(locLy);
  }
  (s.sectors||[]).forEach(function(sec){
    if(!sec.north)return;
    L.rectangle([[sec.south,sec.west],[sec.north,sec.east]],{
      color:'#334455',weight:1,fillOpacity:.03,dashArray:'4,4'}).bindTooltip(sec.name+' ('+sec.terrain+')').addTo(sectorLy);
  });
  (s.sam_sites||[]).forEach(function(sam){
    if(!sam.lat)return;
    var cl=sam.faction==='india'?'#2196F3':'#4CAF50';
    L.circle([sam.lat,sam.lon],{radius:(sam.range_km||50)*1000,color:cl,weight:1,dashArray:'5,5',
      fillColor:cl,fillOpacity:.07}).bindTooltip(sam.name+' ('+sam.type+', '+sam.range_km+'km)').addTo(samLy);
  });
  (s.choke_points||[]).forEach(function(cp){
    if(!cp.lat)return;
    L.circleMarker([cp.lat,cp.lon],{radius:4,color:'#cc8844',fillColor:'#cc8844',fillOpacity:.6,weight:1})
     .bindTooltip(cp.name).addTo(locLy);
  });
}

// ── Show turn instantly (no animation) ──
function showTurn(i) {
  turn = Math.max(0, Math.min(i, D.turns.length-1));
  var t = D.turns[turn]; if(!t) return;

  document.getElementById('turn-slider').value = turn;
  document.getElementById('turn-num').textContent = t.turn+'/'+D.max_turns;
  document.getElementById('day-display').textContent = 'Day '+t.day+' '+cap(t.time);
  document.getElementById('weather-display').textContent = cap(t.weather);

  var iV=t.india_vp||0, pV=t.pakistan_vp||0, tot=Math.max(1,iV+pV);
  document.getElementById('india-vp').textContent = iV;
  document.getElementById('pakistan-vp').textContent = pV;
  document.getElementById('vp-india-bar').style.width = (iV/tot*100)+'%';
  document.getElementById('vp-pak-bar').style.width = (pV/tot*100)+'%';

  drawUnits(t);
  drawCombatMarkers(t);
}

function drawUnits(t) {
  unitLy.clearLayers();
  (t.units||[]).forEach(function(u){
    if(u.lat==null) return;
    var cl=u.faction==='india'?'#2196F3':'#4CAF50';
    var sz=catSize[u.category]||6;
    var op=u.status==='destroyed'?.2:u.status==='damaged'?.5:.85;
    L.marker([u.lat,u.lon],{icon:L.divIcon({className:'unit-icon',
      html:'<div style="width:'+sz+'px;height:'+sz+'px;background:'+cl+';border-radius:50%;opacity:'+op+';border:1px solid rgba(255,255,255,.3)"></div>',
      iconSize:[sz,sz],iconAnchor:[sz/2,sz/2]})})
     .bindTooltip('<b>'+esc(u.name)+'</b><br>Type: '+esc(u.type)+'<br>'+u.category+' | '+u.status+'<br>Strength: '+u.strength+'%')
     .addTo(unitLy);
  });
}

function drawCombatMarkers(t) {
  combatLy.clearLayers();
  (t.combat_events||[]).forEach(function(e){
    if(e.lat==null) return;
    L.marker([e.lat,e.lon],{icon:L.divIcon({className:'combat-pulse',
      html:'<div class="combat-dot"></div>',iconSize:[18,18],iconAnchor:[9,9]})})
     .bindTooltip('<b>'+esc(e.phase)+'</b><br>'+esc(e.attacker)+' vs '+esc(e.defender)+'<br>Result: '+esc(e.result)+
       (e.notes&&e.notes.length?'<br><i>'+e.notes.map(esc).join('<br>')+'</i>':''))
     .addTo(combatLy);
  });
}

function feedReasoning(t) {
  // Add reasoning to each faction's feed
  if(!feedPak) feedInit();
  var pakR = t.pakistan_reasoning || '';
  var indR = t.india_reasoning || '';
  if(pakR) {
    feedRemoveCursor(feedPak);
    var tog = document.createElement('div');
    tog.className = 'feed-reasoning-toggle';
    tog.textContent = '\u25b8 COMMAND REASONING';
    tog.onclick = function(){ var r=this.nextElementSibling; r.style.display=r.style.display==='none'?'block':'none'; };
    feedPak.appendChild(tog);
    var div = document.createElement('div');
    div.className = 'feed-reasoning';
    div.textContent = pakR;
    feedPak.appendChild(div);
    feedAddCursor(feedPak);
  }
  if(indR) {
    feedRemoveCursor(feedInd);
    var tog2 = document.createElement('div');
    tog2.className = 'feed-reasoning-toggle';
    tog2.textContent = '\u25b8 COMMAND REASONING';
    tog2.onclick = function(){ var r=this.nextElementSibling; r.style.display=r.style.display==='none'?'block':'none'; };
    feedInd.appendChild(tog2);
    var div2 = document.createElement('div');
    div2.className = 'feed-reasoning';
    div2.textContent = indR;
    feedInd.appendChild(div2);
    feedAddCursor(feedInd);
  }
}

// ── Battle Feed (split: Pakistan left, India right) ──
var feedPak, feedInd;
function feedInit() {
  feedPak = document.getElementById('feed-pakistan');
  feedInd = document.getElementById('feed-india');
}

function getFeedEl(faction) {
  return faction === 'india' ? feedInd : feedPak;
}

function feedClear() {
  if(!feedPak) feedInit();
  feedPak.innerHTML = '<div class="feed-col-label pakistan">PAKISTAN</div>';
  feedInd.innerHTML = '<div class="feed-col-label india">INDIA</div>';
  feedAddCursor(feedPak);
  feedAddCursor(feedInd);
}

function feedAddCursor(el) {
  var c = document.createElement('span');
  c.className = 'feed-cursor';
  el.appendChild(c);
  el.scrollTop = el.scrollHeight;
}

function feedRemoveCursor(el) {
  var cur = el.querySelector('.feed-cursor');
  if(cur) cur.remove();
}

function feedLine(text, colorClass, tag, faction) {
  if(!feedPak) feedInit();
  // Determine target: specific faction or both
  var targets = [];
  if(faction === 'india') targets = [feedInd];
  else if(faction === 'pakistan') targets = [feedPak];
  else targets = [feedPak, feedInd];

  targets.forEach(function(el) {
    feedRemoveCursor(el);
    var div = document.createElement('div');
    div.className = 'feed-line ' + (colorClass || 'fc-white');
    div.textContent = text;
    if(tag) {
      var sp = document.createElement('span');
      sp.className = 'feed-tag';
      sp.textContent = tag;
      div.appendChild(sp);
    }
    el.appendChild(div);
    feedAddCursor(el);
  });
}

function feedPhaseHeader(text, color, faction) {
  if(!feedPak) feedInit();
  var targets = [];
  if(faction === 'india') targets = [feedInd];
  else if(faction === 'pakistan') targets = [feedPak];
  else targets = [feedPak, feedInd];

  targets.forEach(function(el) {
    feedRemoveCursor(el);
    var div = document.createElement('div');
    div.className = 'feed-phase';
    div.style.color = color || '#ccddee';
    div.textContent = '\u2501\u2501 ' + text + ' \u2501\u2501';
    el.appendChild(div);
    feedAddCursor(el);
  });
  sfx.phaseChime();
}

function feedSeparator(faction) {
  if(!feedPak) feedInit();
  var targets = [];
  if(faction === 'india') targets = [feedInd];
  else if(faction === 'pakistan') targets = [feedPak];
  else targets = [feedPak, feedInd];

  targets.forEach(function(el) {
    var div = document.createElement('div');
    div.className = 'feed-sep';
    el.appendChild(div);
  });
}

function eventToFeedLines(ev) {
  var pd = phaseFor(ev);
  var isVic = ev.result && ev.result.indexOf('victory') >= 0;
  var isDef = ev.result && ev.result.indexOf('defeat') >= 0;
  var isStalem = ev.result && ev.result.indexOf('stalemate') >= 0;
  var fColor = ev.attacker_faction === 'india' ? 'fc-cyan' : 'fc-green';
  var sfxMap = {missile:'missile',air:'air',drone:'drone',arty:'arty',heli:'heli',ground:'arty',sf:'sf'};
  var sfxType = sfxMap[pd.type] || 'default';
  var actionMap = {missile:'MISSILE LAUNCH',air:'AIR SORTIE',drone:'DRONE STRIKE',arty:'FIRE MISSION',heli:'HELI OPS',ground:'GROUND ASSAULT',sf:'SF OPS'};
  var action = actionMap[pd.type] || 'ENGAGE';
  var faction = ev.attacker_faction || 'india';
  var facLabel = faction === 'india' ? '[INDIA]' : '[PAK]';
  var lines = [];

  // Action line with sfx and richer formatting
  lines.push({text:'\u25b8 '+action+' \u2014 '+fmtUnit(ev.attacker)+' '+facLabel, color:fColor, faction:faction, sfx:sfxType});

  // Target line
  if(ev.defender) {
    lines.push({text:'  \u21b3 Target: '+fmtUnit(ev.defender), color:'fc-white', faction:faction});
  }

  // Intercept-attempt line if notes mention intercept
  var hasIntercept = ev.notes && ev.notes.some(function(n){ return /intercept/i.test(n); });
  if(hasIntercept) {
    lines.push({text:'  \u25b8 BMD INTERCEPT \u2014 engaging...', color:'fc-amber', faction:faction, sfx:'default', delay:600});
  }

  return {opening: lines, closing: eventResultLines(ev, isVic, isDef, isStalem, faction), faction: faction};
}

function eventResultLines(ev, isVic, isDef, isStalem, faction) {
  var lines = [];
  var sym = isVic ? '\u2726' : isDef ? '\u2717' : '\u2014';
  var rColor = isVic ? 'fc-green' : isDef ? 'fc-red' : 'fc-amber';
  var resultText = (ev.result||'engaged').toUpperCase();
  var sfxResult = isVic ? 'success' : isDef ? 'fail' : 'default';
  lines.push({text:'  '+sym+' '+resultText, color:rColor, faction:faction, sfx:sfxResult});
  if(ev.notes && ev.notes.length) {
    ev.notes.forEach(function(n){
      // Color-code individual note lines by content
      var nLower = n.toLowerCase();
      var nColor = rColor;
      if(/destroy|kill|lost|shot down|wipe|cratered|penetrat/.test(nLower)) nColor = 'fc-red';
      else if(/success|intercept|secured|complete|confirm/.test(nLower)) nColor = 'fc-green';
      else if(/track|detect|surveil|intel|map/.test(nLower)) nColor = 'fc-amber';
      lines.push({text:'    '+n, color:nColor, faction:faction});
    });
  }
  return lines;
}

async function streamFeedLines(lines, ctx, delayMs) {
  for(var i=0;i<lines.length;i++){
    if(ctx && ctx.cancelled) return;
    feedLine(lines[i].text, lines[i].color, lines[i].tag, lines[i].faction);
    // Dispatch sfx per line
    var s = lines[i].sfx;
    if(s==='missile') sfx.missileLaunch();
    else if(s==='air') sfx.jetFlyby();
    else if(s==='drone') sfx.droneBuzz();
    else if(s==='arty') sfx.artyBoom();
    else if(s==='heli') sfx.heliRotor();
    else if(s==='sf') sfx.sfSilenced();
    else if(s==='fail') sfx.explosion(false);
    else if(s==='success') sfx.interceptHit();
    else sfx.feedTick();
    var d = lines[i].delay || delayMs || 60;
    if(i < lines.length-1) await sleep(d/animSpeed);
  }
}

function feedTurnSummary(t) {
  // Static feed for non-animated viewing
  feedClear();
  feedLine('TURN '+t.turn+' \u2014 DAY '+t.day+' '+t.time.toUpperCase(), 'fc-dim');
  feedSeparator();

  // Add reasoning
  feedReasoning(t);

  var events = t.combat_events||[];
  if(events.length === 0) {
    feedLine('No combat this turn', 'fc-dim');
    return;
  }

  // Group by phase
  var used = {};
  for(var pi=0; pi<PHASE_DEFS.length; pi++){
    var pd = PHASE_DEFS[pi];
    var grp = [];
    for(var ei=0; ei<events.length; ei++){
      if(used[ei]) continue;
      if(pd.match.test(events[ei].phase)){grp.push(events[ei]);used[ei]=true;}
    }
    if(grp.length===0) continue;
    feedPhaseHeader(pd.label, pd.color);
    grp.forEach(function(ev){
      var fl = eventToFeedLines(ev);
      fl.opening.forEach(function(l){feedLine(l.text,l.color,l.tag,l.faction);});
      fl.closing.forEach(function(l){feedLine(l.text,l.color,l.tag,l.faction);});
    });
    feedSeparator();
  }
}

// ── Animation engine ──
function sleep(ms) { return new Promise(function(r){ setTimeout(r, ms); }); }
function lerp(a,b,t) { return a+(b-a)*t; }
function easeInOut(t) { return t<.5 ? 2*t*t : 1-Math.pow(-2*t+2,2)/2; }

function cancelAnim() {
  if(currentAnim) currentAnim.cancelled = true;
  animLy.clearLayers();
  hidePhaseLabel();
}

function showPhaseLabel(text, color) {
  var el = document.getElementById('phase-overlay');
  el.textContent = text; el.style.color = color;
  el.style.borderColor = color; el.style.display = 'block';
}
function hidePhaseLabel() {
  document.getElementById('phase-overlay').style.display = 'none';
}

// ── Sound effects (Web Audio API) ──
var soundOn = true;
var sfx = {
  ctx: null,
  init: function() { this.ctx = new (window.AudioContext || window.webkitAudioContext)(); },
  ensure: function() {
    if(!this.ctx) this.init();
    if(this.ctx.state==='suspended') this.ctx.resume();
  },
  _noise: function(dur, shape) {
    // Shaped noise buffer: shape controls decay curve
    var c=this.ctx, len=Math.floor(c.sampleRate*dur);
    var buf=c.createBuffer(1,len,c.sampleRate), d=buf.getChannelData(0);
    for(var i=0;i<len;i++){
      var t=i/len;
      var env = shape==='punch' ? Math.exp(-t*8) :
                shape==='rumble' ? Math.exp(-t*2)*(1+0.3*Math.sin(t*30)) :
                shape==='crack' ? (t<0.02?1:Math.exp(-(t-0.02)*12)) :
                shape==='sustained' ? Math.sin(Math.PI*t)*Math.exp(-t*1.5) :
                Math.exp(-t*4);
      d[i]=(Math.random()*2-1)*env;
    }
    return buf;
  },
  _play: function(buf, filterType, freqStart, freqEnd, dur, gain, delay) {
    var c=this.ctx, t0=c.currentTime+(delay||0);
    var s=c.createBufferSource(); s.buffer=buf;
    var f=c.createBiquadFilter(); f.type=filterType;
    f.frequency.setValueAtTime(freqStart, t0);
    if(freqEnd!==freqStart) f.frequency.exponentialRampToValueAtTime(Math.max(20,freqEnd), t0+dur);
    f.Q.value = filterType==='bandpass' ? 2 : 1;
    var g=c.createGain();
    g.gain.setValueAtTime(gain, t0);
    g.gain.exponentialRampToValueAtTime(0.001, t0+dur);
    s.connect(f); f.connect(g); g.connect(c.destination);
    s.start(t0);
  },
  missileLaunch: function() {
    if(!soundOn) return; this.ensure(); var c=this.ctx;
    // Layer 1: Deep ignition thump
    this._play(this._noise(0.3,'punch'), 'lowpass', 120, 40, 0.3, 0.25, 0);
    // Layer 2: Rising rocket whoosh
    this._play(this._noise(1.2,'sustained'), 'bandpass', 300, 4000, 1.2, 0.15, 0.05);
    // Layer 3: Sustained motor burn (low roar)
    this._play(this._noise(1.5,'rumble'), 'lowpass', 200, 80, 1.5, 0.12, 0.1);
    // Layer 4: High-freq sizzle
    this._play(this._noise(0.8,'crack'), 'highpass', 3000, 6000, 0.8, 0.04, 0.02);
  },
  explosion: function(big) {
    if(!soundOn) return; this.ensure(); var c=this.ctx, t0=c.currentTime;
    var dur = big ? 2.5 : 1.2;
    // Layer 1: Sub-bass punch (gut-shaker)
    var o=c.createOscillator(), g=c.createGain();
    o.type='sine';
    o.frequency.setValueAtTime(big?35:50, t0);
    o.frequency.exponentialRampToValueAtTime(20, t0+0.4);
    g.gain.setValueAtTime(big?0.5:0.3, t0);
    g.gain.exponentialRampToValueAtTime(0.001, t0+0.5);
    o.connect(g); g.connect(c.destination); o.start(t0); o.stop(t0+0.5);
    // Layer 2: Mid-range blast crack
    this._play(this._noise(0.15,'crack'), 'bandpass', big?400:600, big?200:300, 0.2, big?0.4:0.25, 0);
    // Layer 3: Low rumble tail
    this._play(this._noise(dur,'rumble'), 'lowpass', big?250:350, 40, dur, big?0.2:0.1, 0.05);
    // Layer 4: Debris scatter (delayed crackle)
    this._play(this._noise(big?1.5:0.6,'punch'), 'highpass', 1500, 800, big?1.5:0.6, big?0.06:0.03, 0.15);
    // Layer 5: Distant echo (big only)
    if(big) this._play(this._noise(1.8,'rumble'), 'lowpass', 150, 30, 1.8, 0.08, 0.4);
  },
  jetFlyby: function() {
    if(!soundOn) return; this.ensure(); var c=this.ctx, t0=c.currentTime;
    // Layer 1: Turbine whine (doppler sweep)
    var o=c.createOscillator(), g=c.createGain();
    o.type='sawtooth';
    o.frequency.setValueAtTime(180, t0);
    o.frequency.exponentialRampToValueAtTime(800, t0+0.4);
    o.frequency.exponentialRampToValueAtTime(120, t0+1.2);
    g.gain.setValueAtTime(0.03, t0);
    g.gain.linearRampToValueAtTime(0.1, t0+0.35);
    g.gain.exponentialRampToValueAtTime(0.001, t0+1.2);
    var f=c.createBiquadFilter(); f.type='lowpass'; f.frequency.value=3000;
    o.connect(f); f.connect(g); g.connect(c.destination); o.start(t0); o.stop(t0+1.3);
    // Layer 2: Broadband jet wash
    this._play(this._noise(1.4,'sustained'), 'bandpass', 200, 150, 1.4, 0.08, 0);
    // Layer 3: High-freq compressor whine
    this._play(this._noise(0.8,'sustained'), 'highpass', 4000, 2000, 0.8, 0.03, 0.1);
  },
  radarPing: function() {
    if(!soundOn) return; this.ensure(); var c=this.ctx, t0=c.currentTime;
    // Two-tone sweep like real radar
    var o=c.createOscillator(), g=c.createGain();
    o.type='sine';
    o.frequency.setValueAtTime(1200, t0);
    o.frequency.exponentialRampToValueAtTime(1800, t0+0.08);
    g.gain.setValueAtTime(0.1, t0);
    g.gain.exponentialRampToValueAtTime(0.001, t0+0.35);
    o.connect(g); g.connect(c.destination); o.start(t0); o.stop(t0+0.35);
    // Second ping (echo)
    var o2=c.createOscillator(), g2=c.createGain();
    o2.type='sine'; o2.frequency.value=1500;
    g2.gain.setValueAtTime(0.04, t0+0.12);
    g2.gain.exponentialRampToValueAtTime(0.001, t0+0.4);
    o2.connect(g2); g2.connect(c.destination); o2.start(t0+0.12); o2.stop(t0+0.4);
  },
  interceptHit: function() {
    if(!soundOn) return; this.ensure(); var c=this.ctx;
    // Sharp metallic crack
    this._play(this._noise(0.08,'crack'), 'highpass', 2000, 4000, 0.1, 0.35, 0);
    // Mid-range burst
    this._play(this._noise(0.3,'punch'), 'bandpass', 800, 400, 0.3, 0.2, 0.02);
    // Metallic ring
    var o=c.createOscillator(), g=c.createGain();
    o.type='sine'; o.frequency.value=3200;
    g.gain.setValueAtTime(0.06, c.currentTime);
    g.gain.exponentialRampToValueAtTime(0.001, c.currentTime+0.5);
    o.connect(g); g.connect(c.destination); o.start(); o.stop(c.currentTime+0.5);
    // Debris scatter
    this._play(this._noise(0.6,'punch'), 'highpass', 1200, 600, 0.6, 0.05, 0.08);
  },
  artyBoom: function() {
    if(!soundOn) return; this.ensure(); var c=this.ctx, t0=c.currentTime;
    // Layer 1: Deep thump
    var o=c.createOscillator(), g=c.createGain();
    o.type='sine';
    o.frequency.setValueAtTime(55, t0);
    o.frequency.exponentialRampToValueAtTime(25, t0+0.3);
    g.gain.setValueAtTime(0.35, t0);
    g.gain.exponentialRampToValueAtTime(0.001, t0+0.35);
    o.connect(g); g.connect(c.destination); o.start(t0); o.stop(t0+0.4);
    // Layer 2: Blast crack
    this._play(this._noise(0.1,'crack'), 'bandpass', 500, 200, 0.15, 0.3, 0);
    // Layer 3: Rolling rumble
    this._play(this._noise(1.5,'rumble'), 'lowpass', 200, 50, 1.5, 0.1, 0.05);
  },
  droneBuzz: function() {
    if(!soundOn) return; this.ensure(); var c=this.ctx, t0=c.currentTime;
    // Layer 1: Motor hum (multi-rotor signature)
    var o=c.createOscillator(), g=c.createGain();
    o.type='sawtooth';
    o.frequency.setValueAtTime(280, t0);
    o.frequency.linearRampToValueAtTime(320, t0+0.3);
    o.frequency.linearRampToValueAtTime(260, t0+1.0);
    g.gain.setValueAtTime(0.05, t0);
    g.gain.linearRampToValueAtTime(0.07, t0+0.2);
    g.gain.exponentialRampToValueAtTime(0.001, t0+1.0);
    var f=c.createBiquadFilter(); f.type='lowpass'; f.frequency.value=1200;
    o.connect(f); f.connect(g); g.connect(c.destination); o.start(t0); o.stop(t0+1.1);
    // Layer 2: Prop wash (broadband noise)
    this._play(this._noise(1.0,'sustained'), 'bandpass', 800, 600, 1.0, 0.04, 0);
    // Layer 3: High-freq propeller harmonics
    var o2=c.createOscillator(), g2=c.createGain();
    o2.type='square'; o2.frequency.value=560;
    g2.gain.setValueAtTime(0.02, t0);
    g2.gain.exponentialRampToValueAtTime(0.001, t0+0.8);
    var f2=c.createBiquadFilter(); f2.type='lowpass'; f2.frequency.value=2000;
    o2.connect(f2); f2.connect(g2); g2.connect(c.destination); o2.start(t0); o2.stop(t0+0.9);
  },
  heliRotor: function() {
    if(!soundOn) return; this.ensure(); var c=this.ctx, t0=c.currentTime;
    // Layer 1: Blade chop (rhythmic thumps)
    for(var i=0;i<8;i++){
      var t=t0+i*0.07;
      var o=c.createOscillator(), g=c.createGain();
      o.type='triangle';
      o.frequency.setValueAtTime(60+Math.random()*15, t);
      g.gain.setValueAtTime(0.12, t);
      g.gain.exponentialRampToValueAtTime(0.001, t+0.05);
      o.connect(g); g.connect(c.destination); o.start(t); o.stop(t+0.05);
    }
    // Layer 2: Turbine whine
    var o2=c.createOscillator(), g2=c.createGain();
    o2.type='sawtooth'; o2.frequency.value=1400;
    g2.gain.setValueAtTime(0.03, t0);
    g2.gain.exponentialRampToValueAtTime(0.001, t0+0.7);
    var f=c.createBiquadFilter(); f.type='lowpass'; f.frequency.value=2500;
    o2.connect(f); f.connect(g2); g2.connect(c.destination); o2.start(t0); o2.stop(t0+0.7);
    // Layer 3: Rotor wash
    this._play(this._noise(0.8,'sustained'), 'lowpass', 300, 100, 0.8, 0.06, 0);
  },
  sfSilenced: function() {
    if(!soundOn) return; this.ensure(); var c=this.ctx, t0=c.currentTime;
    // Suppressed shots: sharp transient + muffled thud
    for(var i=0;i<3;i++){
      var t=t0+i*0.18;
      // Transient click
      this._play(this._noise(0.02,'crack'), 'bandpass', 2000, 1000, 0.04, 0.15, i*0.18);
      // Muffled body
      this._play(this._noise(0.12,'punch'), 'lowpass', 400, 150, 0.15, 0.08, i*0.18+0.01);
    }
    // Subtle mechanical action
    var o=c.createOscillator(), g=c.createGain();
    o.type='sine'; o.frequency.value=800;
    g.gain.setValueAtTime(0.02, t0+0.55);
    g.gain.exponentialRampToValueAtTime(0.001, t0+0.65);
    o.connect(g); g.connect(c.destination); o.start(t0+0.55); o.stop(t0+0.65);
  },
  feedTick: function() {
    if(!soundOn) return; this.ensure(); var c=this.ctx, t0=c.currentTime;
    var o=c.createOscillator(), g=c.createGain();
    o.type='sine'; o.frequency.value=1000;
    g.gain.setValueAtTime(0.015, t0);
    g.gain.exponentialRampToValueAtTime(0.001, t0+0.03);
    o.connect(g); g.connect(c.destination); o.start(t0); o.stop(t0+0.03);
  },
  ewBuzz: function() {
    if(!soundOn) return; this.ensure(); var c=this.ctx;
    this._play(this._noise(0.08,'crack'), 'bandpass', 2500, 1500, 0.1, 0.06, 0);
  },
  phaseChime: function() {
    if(!soundOn) return; this.ensure(); var c=this.ctx, t0=c.currentTime;
    var o1=c.createOscillator(), g1=c.createGain();
    o1.type='sine'; o1.frequency.value=800;
    g1.gain.setValueAtTime(0.06, t0);
    g1.gain.exponentialRampToValueAtTime(0.001, t0+0.3);
    o1.connect(g1); g1.connect(c.destination); o1.start(t0); o1.stop(t0+0.3);
    var o2=c.createOscillator(), g2=c.createGain();
    o2.type='sine'; o2.frequency.value=1200;
    g2.gain.setValueAtTime(0.06, t0+0.15);
    g2.gain.exponentialRampToValueAtTime(0.001, t0+0.45);
    o2.connect(g2); g2.connect(c.destination); o2.start(t0+0.15); o2.stop(t0+0.45);
  }
};

function toggleSound() {
  soundOn = !soundOn;
  document.getElementById('sound-btn').innerHTML = soundOn ? '&#128264;' : '&#128263;';
}

function toggleCRT() {
  var el = document.getElementById('crt-overlay');
  el.classList.toggle('active');
  document.getElementById('crt-btn').classList.toggle('active');
}

// ── Screen shake ──
function screenShake(intensity) {
  var el = document.getElementById('map');
  var start = performance.now();
  var dur = 400 / animSpeed;
  function shakeStep(ts) {
    var elapsed = ts - start;
    if(elapsed > dur) { el.style.transform = ''; return; }
    var decay = 1 - elapsed / dur;
    var x = (Math.random()-.5) * intensity * decay * 2;
    var y = (Math.random()-.5) * intensity * decay * 2;
    el.style.transform = 'translate('+x+'px,'+y+'px)';
    requestAnimationFrame(shakeStep);
  }
  requestAnimationFrame(shakeStep);
}

// ── Engagement labels on map ──
function showMapLabel(latlng, text, cssClass, duration) {
  var m = L.marker(latlng, {icon: L.divIcon({
    className:'anim-icon',
    html:'<div class="'+cssClass+'">'+text+'</div>',
    iconSize:[500,28], iconAnchor:[250,-18]
  })}).addTo(animLy);
  setTimeout(function(){ try{animLy.removeLayer(m);}catch(e){} }, (duration||2500)/animSpeed);
  return m;
}

function showFloatText(latlng, text, colorClass, size) {
  var cls = 'float-text';
  if(size==='large') cls += ' ft-large';
  else if(size==='small') cls += ' ft-small';
  if(colorClass) cls += ' '+colorClass;
  var m = L.marker(latlng, {icon: L.divIcon({
    className:'anim-icon',
    html:'<div class="'+cls+'">'+text+'</div>',
    iconSize:[400,24], iconAnchor:[200,-10]
  })}).addTo(animLy);
  setTimeout(function(){ try{animLy.removeLayer(m);}catch(e){} }, 3500/animSpeed);
  return m;
}

function resultFloatText(ev) {
  if(ev.lat==null) return;
  var pos = [ev.lat, ev.lon];
  var isVic = ev.result && ev.result.indexOf('victory') >= 0;
  var isDef = ev.result && ev.result.indexOf('defeat') >= 0;
  var note = evNote(ev);
  var colorCls = isVic ? 'ft-green' : isDef ? 'ft-red' : 'ft-amber';
  var hasKill = /destroy|kill|shot down|wipe|crater/i.test(note);
  var sz = hasKill ? 'large' : 'small';
  var txt = note || (isVic ? 'TARGET HIT' : isDef ? 'FAILED' : 'ENGAGED');
  // Truncate long text
  if(txt.length > 50) txt = txt.substring(0, 47) + '...';
  showFloatText(pos, txt, colorCls, sz);
}

// ── Explosion & flash makers ──
function mkExplosion(latlng, small) {
  if(small) {
    return L.marker(latlng, {icon: L.divIcon({
      className:'anim-icon', html:'<div class="boom-sm"></div>',
      iconSize:[36,36], iconAnchor:[18,18]
    })});
  }
  return L.marker(latlng, {icon: L.divIcon({
    className:'anim-icon',
    html:'<div class="boom-wrap"><div class="boom-smoke"></div><div class="boom-ring"></div><div class="boom-core"></div></div>',
    iconSize:[80,80], iconAnchor:[40,40]
  })});
}

function mkFlash(latlng) {
  return L.marker(latlng, {icon: L.divIcon({
    className:'anim-icon',
    html:'<div class="ground-flash-wrap"><div class="ground-flash-ring"></div><div class="ground-flash-core"></div></div>',
    iconSize:[60,60], iconAnchor:[30,30]
  })});
}

// SVG missile icon builders
function mkMissileSvg(color, size, type) {
  var w = size || 28, h = Math.round(w * 0.4);
  if (type === 'sam') {
    // Slim interceptor
    return '<svg viewBox="0 0 28 8" width="'+w+'" height="'+h+'" style="overflow:visible">'
      +'<defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">'
      +'<stop offset="0%" stop-color="'+color+'"/><stop offset="100%" stop-color="'+color+'" stop-opacity=".5"/></linearGradient></defs>'
      +'<path d="M27,4 L22,1.5 L3,2 L0,4 L3,6 L22,6.5 Z" fill="url(#sg)" stroke="rgba(255,255,255,.3)" stroke-width=".5"/>'
      +'<polygon points="5,0.5 7,2.5 5,2" fill="'+color+'" opacity=".7"/>'
      +'<polygon points="5,7.5 7,5.5 5,6" fill="'+color+'" opacity=".7"/>'
      +'</svg>';
  }
  if (type === 'ballistic') {
    // Fatter ballistic missile with fins
    return '<svg viewBox="0 0 30 14" width="'+w+'" height="'+h+'" style="overflow:visible">'
      +'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
      +'<stop offset="0%" stop-color="'+color+'"/><stop offset="100%" stop-color="'+color+'" stop-opacity=".4"/></linearGradient></defs>'
      +'<ellipse cx="15" cy="7" rx="14" ry="5" fill="url(#bg)" stroke="rgba(255,255,255,.25)" stroke-width=".5"/>'
      +'<path d="M29,7 L24,3 L24,11 Z" fill="'+color+'"/>'
      +'<polygon points="3,0 6,4 3,3" fill="'+color+'" opacity=".8"/>'
      +'<polygon points="3,14 6,10 3,11" fill="'+color+'" opacity=".8"/>'
      +'<rect x="2" y="2" width="1.5" height="3" rx=".5" fill="'+color+'" opacity=".6"/>'
      +'<rect x="2" y="9" width="1.5" height="3" rx=".5" fill="'+color+'" opacity=".6"/>'
      +'</svg>';
  }
  // Default: cruise missile (sleek with small wings)
  return '<svg viewBox="0 0 32 12" width="'+w+'" height="'+h+'" style="overflow:visible">'
    +'<defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1">'
    +'<stop offset="0%" stop-color="'+color+'"/><stop offset="100%" stop-color="'+color+'" stop-opacity=".5"/></linearGradient></defs>'
    +'<path d="M31,6 L24,1.5 L4,2.5 L0,6 L4,9.5 L24,10.5 Z" fill="url(#cg)" stroke="rgba(255,255,255,.3)" stroke-width=".5"/>'
    +'<polygon points="14,0 18,3.5 14,2.5" fill="'+color+'" opacity=".6"/>'
    +'<polygon points="14,12 18,8.5 14,9.5" fill="'+color+'" opacity=".6"/>'
    +'<polygon points="4,1 7,3 4,2.5" fill="'+color+'" opacity=".7"/>'
    +'<polygon points="4,11 7,9 4,9.5" fill="'+color+'" opacity=".7"/>'
    +'</svg>';
}

function mkMissileIcon(from, to, color, size, missileType) {
  var ang = -Math.atan2(to[0]-from[0], to[1]-from[1])*180/Math.PI;
  var svg = mkMissileSvg(color, size || 28, missileType);
  var w = size || 28, h = Math.round(w * 0.4);
  return '<div style="position:relative;transform:rotate('+ang+'deg);transform-origin:center">'
    + svg + '<div class="missile-exhaust"></div></div>';
}

// Animate a projectile from A to B with trail
function flyObject(from, to, opts, ctx) {
  return new Promise(function(resolve) {
    if(ctx.cancelled){resolve();return;}
    var dur = (opts.duration||1500) / animSpeed;
    var start = null;

    // Trail
    var trail = L.polyline([], {
      color: opts.trailColor||'#ff4444', weight: opts.trailWeight||2,
      opacity: opts.trailOpacity||.7, dashArray: opts.trailDash||null
    }).addTo(animLy);

    // Moving head
    var head;
    if(opts.missile) {
      var mhtml = mkMissileIcon(from, to, opts.missileColor||opts.trailColor||'#ff4444',
                                opts.missileSize||28, opts.missileType||'cruise');
      head = L.marker(from, {icon:L.divIcon({className:'anim-icon',
        html:mhtml, iconSize:[opts.missileSize||28,(opts.missileSize||28)*0.5],
        iconAnchor:[(opts.missileSize||28)/2,(opts.missileSize||28)*0.25]})});
    } else if(opts.plane) {
      var ang = -Math.atan2(to[0]-from[0], to[1]-from[1])*180/Math.PI;
      head = L.marker(from, {icon:L.divIcon({className:'anim-icon',
        html:'<div style="font-size:'+(opts.planeSize||14)+'px;color:'+(opts.trailColor||'#4499ff')+';transform:rotate('+ang+'deg);opacity:'+(opts.planeOpacity||1)+'">&#9992;</div>',
        iconSize:[20,20],iconAnchor:[10,10]})});
    } else {
      head = L.circleMarker(from, {
        radius: opts.headRadius||3, color: opts.headColor||'#ffaa00',
        fillColor: opts.headFill||'#ffcc00', fillOpacity:1, weight:1
      });
    }
    head.addTo(animLy);

    function step(ts) {
      if(ctx.cancelled){resolve();return;}
      if(!start) start=ts;
      var raw = Math.min(1,(ts-start)/dur);
      var t = easeInOut(raw);
      var lat = lerp(from[0],to[0],t);
      var lon = lerp(from[1],to[1],t);

      if(head.setLatLng) head.setLatLng([lat,lon]);
      trail.addLatLng([lat,lon]);

      if(raw<1) { requestAnimationFrame(step); }
      else {
        animLy.removeLayer(head);
        resolve();
      }
    }
    requestAnimationFrame(step);
  });
}

// ── SAM interception helpers ──
function haversineKm(lat1, lon1, lat2, lon2) {
  var R = 6371, rad = Math.PI/180;
  var dLat = (lat2-lat1)*rad, dLon = (lon2-lon1)*rad;
  var a = Math.sin(dLat/2)*Math.sin(dLat/2) +
          Math.cos(lat1*rad)*Math.cos(lat2*rad)*Math.sin(dLon/2)*Math.sin(dLon/2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

function findDefendingSam(targetLat, targetLon, attackerFaction) {
  var sams = D.static.sam_sites || [];
  var best = null, bestDist = Infinity;
  for (var i = 0; i < sams.length; i++) {
    var s = sams[i];
    if (s.faction === attackerFaction) continue; // SAMs of same faction don't intercept own missiles
    var dist = haversineKm(s.lat, s.lon, targetLat, targetLon);
    if (dist <= s.range_km && dist < bestDist) {
      best = s; bestDist = dist;
    }
  }
  return best;
}

function mkInterceptBurst(latlng) {
  return L.marker(latlng, {icon: L.divIcon({
    className:'anim-icon',
    html:'<div class="intercept-wrap"><div class="intercept-ring"></div><div class="intercept-core"></div></div>',
    iconSize:[60,60], iconAnchor:[30,30]
  })});
}

function mkSamMissFlash(latlng) {
  return L.marker(latlng, {icon: L.divIcon({
    className:'anim-icon',
    html:'<div class="sam-miss-flash"></div>',
    iconSize:[24,24], iconAnchor:[12,12]
  })});
}

// ── Drone swarm maker ──
function mkDroneSwarm(latlng) {
  var dots = '';
  for(var i=0;i<8;i++){
    var x=10+Math.random()*40, y=10+Math.random()*40;
    dots+='<div class="drone-dot" style="left:'+x+'px;top:'+y+'px"></div>';
  }
  return L.marker(latlng, {icon:L.divIcon({className:'anim-icon',
    html:'<div class="drone-swarm-wrap">'+dots+'</div>',
    iconSize:[60,60],iconAnchor:[30,30]})});
}
function mkDroneStrikeFlash(latlng) {
  return L.marker(latlng, {icon:L.divIcon({className:'anim-icon',
    html:'<div class="drone-strike-flash"></div>',
    iconSize:[30,30],iconAnchor:[15,15]})});
}

// ── Helicopter maker ──
function mkHeliIcon(latlng, color) {
  return L.marker(latlng, {icon:L.divIcon({className:'anim-icon',
    html:'<div class="heli-rotor-wrap"><div class="heli-rotor" style="background:'+color+'"></div><div class="heli-body" style="color:'+color+'">&#9992;</div></div>',
    iconSize:[40,40],iconAnchor:[20,20]})});
}
function mkHeliStrikeFlash(latlng) {
  return L.marker(latlng, {icon:L.divIcon({className:'anim-icon',
    html:'<div class="heli-strafe-flash"></div>',
    iconSize:[24,24],iconAnchor:[12,12]})});
}

// ── SF ops maker ──
function mkSFPing(latlng) {
  return L.marker(latlng, {icon:L.divIcon({className:'anim-icon',
    html:'<div class="sf-ping-wrap"><div class="sf-ping-ring"></div><div class="sf-ping-core"></div></div>',
    iconSize:[50,50],iconAnchor:[25,25]})});
}

// ── Per-type animations ──
function guessMissileType(ev) {
  var a = (ev.attacker||'').toLowerCase();
  if(a.indexOf('nasr')>=0 || a.indexOf('prithvi')>=0 || a.indexOf('ghauri')>=0 || a.indexOf('shaheen')>=0 || a.indexOf('tbm')>=0)
    return 'ballistic';
  return 'cruise';
}

function fmtUnit(id) {
  return (id||'').replace(/_/g,' ').replace(/^(in|pk)\s/i,'').toUpperCase();
}
function evNote(ev) {
  return (ev.notes && ev.notes.length) ? ev.notes[0] : '';
}

function animMissile(ev, ctx) {
  var from = [ev.from_lat, ev.from_lon], to = [ev.lat, ev.lon];
  var sam = (ev.interceptable !== false) ? findDefendingSam(ev.lat, ev.lon, ev.attacker_faction) : null;
  var mType = guessMissileType(ev);
  var mColor = ev.attacker_faction === 'india' ? '#ff6644' : '#ff4444';
  var aName = fmtUnit(ev.attacker);
  var note = evNote(ev);

  // Launch label with target info + sound
  showMapLabel(from, aName+' LAUNCHED', 'engage-label', 2500);
  // Show target marker
  showMapLabel(to, 'INCOMING — '+fmtUnit(ev.defender), 'engage-label', 3000);
  sfx.missileLaunch();

  if (!sam) {
    return flyObject(from, to, {
      duration:1800, trailColor:mColor, trailWeight:2,
      missile:true, missileColor:mColor, missileSize:28, missileType:mType
    }, ctx).then(function(){
      if(ctx.cancelled) return;
      mkExplosion(to, false).addTo(animLy);
      sfx.explosion(true); screenShake(8);
      var hitMsg = note || (aName+' HIT');
      showMapLabel(to, hitMsg, 'kill-label', 3000);
      return sleep(900/animSpeed);
    });
  }

  // SAM in range — animate interception attempt
  var isKill = ev.result.indexOf('defeat') >= 0 || ev.result.indexOf('stalemate') >= 0;
  var interceptT = 0.65;
  var interceptPt = [lerp(from[0], to[0], interceptT), lerp(from[1], to[1], interceptT)];
  var samPos = [sam.lat, sam.lon];
  var samColor = sam.faction === 'india' ? '#2196F3' : '#4CAF50';

  // SAM site activation
  L.circleMarker(samPos, {radius:8, color:samColor, weight:2, fillColor:samColor, fillOpacity:0.4}).addTo(animLy);
  showMapLabel(samPos, sam.type.toUpperCase()+' TRACKING', 'engage-label', 2500);
  sfx.radarPing();

  if (isKill) {
    return Promise.all([
      flyObject(from, interceptPt, {
        duration:1400, trailColor:mColor, trailWeight:2,
        missile:true, missileColor:mColor, missileSize:28, missileType:mType
      }, ctx),
      sleep(500/animSpeed).then(function() {
        if(ctx.cancelled) return;
        showMapLabel(samPos, sam.type.toUpperCase()+' FIRES', 'engage-label', 1800);
        sfx.missileLaunch();
        return flyObject(samPos, interceptPt, {
          duration:1000, trailColor:samColor, trailWeight:1.5, trailDash:'4,3',
          missile:true, missileColor:samColor, missileSize:20, missileType:'sam'
        }, ctx);
      })
    ]).then(function(){
      if(ctx.cancelled) return;
      mkInterceptBurst(interceptPt).addTo(animLy);
      sfx.interceptHit(); screenShake(5);
      showMapLabel(interceptPt, aName+' INTERCEPTED BY '+sam.type.toUpperCase(), 'intercept-label', 3000);
      return sleep(1000/animSpeed);
    });
  } else {
    return Promise.all([
      flyObject(from, to, {
        duration:1800, trailColor:mColor, trailWeight:2,
        missile:true, missileColor:mColor, missileSize:28, missileType:mType
      }, ctx),
      sleep(400/animSpeed).then(function() {
        if(ctx.cancelled) return;
        showMapLabel(samPos, sam.type.toUpperCase()+' FIRES', 'engage-label', 1800);
        sfx.missileLaunch();
        var missPt = [interceptPt[0]+(Math.random()-.5)*.08, interceptPt[1]+(Math.random()-.5)*.08];
        return flyObject(samPos, missPt, {
          duration:1000, trailColor:samColor, trailWeight:1.5, trailDash:'4,3',
          missile:true, missileColor:samColor, missileSize:20, missileType:'sam'
        }, ctx).then(function(){
          if(ctx.cancelled) return;
          mkSamMissFlash(missPt).addTo(animLy);
          showMapLabel(missPt, 'MISS', 'engage-label', 1500);
        });
      })
    ]).then(function(){
      if(ctx.cancelled) return;
      mkExplosion(to, false).addTo(animLy);
      sfx.explosion(true); screenShake(8);
      var hitMsg = note || (aName+' — TARGET HIT');
      showMapLabel(to, hitMsg, 'kill-label', 3000);
      return sleep(900/animSpeed);
    });
  }
}

function animAir(ev, ctx) {
  var from = [ev.from_lat, ev.from_lon], to = [ev.lat, ev.lon];
  var fColor = ev.attacker_faction === 'india' ? '#4499ff' : '#44cc88';
  var aName = fmtUnit(ev.attacker);
  var dName = fmtUnit(ev.defender);
  var note = evNote(ev);
  var standoff = [lerp(from[0], to[0], 0.4), lerp(from[1], to[1], 0.4)];

  // Takeoff label + target indicator + sound
  showMapLabel(from, aName+' SORTIE', 'engage-label', 2500);
  showMapLabel(to, 'TARGET: '+dName, 'engage-label', 3000);
  sfx.jetFlyby();

  // Phase 1: Fly to standoff
  return flyObject(from, standoff, {
    duration:1200, trailColor:fColor, trailWeight:1.5,
    trailDash:'6,4', trailOpacity:.5, plane:true
  }, ctx).then(function(){
    if(ctx.cancelled) return;
    // Phase 2: Fire BVR + RTB simultaneously
    showMapLabel(standoff, aName+' — FOX THREE', 'engage-label', 1800);
    sfx.missileLaunch();
    return Promise.all([
      flyObject(standoff, to, {
        duration:1000, trailColor:'#ffcc44', trailWeight:1.5,
        missile:true, missileColor:'#ffcc44', missileSize:18, missileType:'sam'
      }, ctx).then(function(){
        if(ctx.cancelled) return;
        mkExplosion(to, true).addTo(animLy);
        sfx.explosion(false); screenShake(4);
        var hitText = ev.result.indexOf('victory')>=0 ? (note||'SPLASH ONE — '+dName) : ev.result.indexOf('defeat')>=0 ? 'MISSED — '+dName : 'ENGAGED — '+dName;
        showMapLabel(to, hitText, ev.result.indexOf('victory')>=0?'kill-label':'engage-label', 3000);
        return sleep(500/animSpeed);
      }),
      sleep(200/animSpeed).then(function(){
        if(ctx.cancelled) return;
        return flyObject(standoff, from, {
          duration:1400, trailColor:fColor, trailWeight:1,
          trailDash:'3,6', trailOpacity:.25, plane:true, planeSize:11, planeOpacity:.5
        }, ctx);
      })
    ]);
  });
}

function animArty(ev, ctx) {
  var from = [ev.from_lat, ev.from_lon], to = [ev.lat, ev.lon];
  var aName = fmtUnit(ev.attacker);
  var note = evNote(ev);
  var isCounterBattery = (note||'').toLowerCase().indexOf('counter') >= 0;
  var numRounds = isCounterBattery ? 20 : 12;
  var spreadLat = 0.03, spreadLon = 0.04;  // impact area ~3km x 4km

  // Muzzle flash at gun position
  showMapLabel(from, aName+' — FIRE FOR EFFECT', 'engage-label', 4000);
  mkFlash(from).addTo(animLy);
  sfx.artyBoom();

  var promises = [];
  for(var i=0; i<numRounds; i++) {
    (function(idx){
      var delay = idx * (80 + Math.random()*120); // rapid staggered fire
      promises.push(sleep(delay/animSpeed).then(function(){
        if(ctx.cancelled) return;
        // Random impact within beaten zone
        var jitter = [(Math.random()-.5)*spreadLat, (Math.random()-.5)*spreadLon];
        var target = [to[0]+jitter[0], to[1]+jitter[1]];
        // Shells arc — no visible projectile, just impacts
        return sleep((400 + Math.random()*300)/animSpeed).then(function(){
          if(ctx.cancelled) return;
          mkExplosion(target, true).addTo(animLy);
          sfx.artyBoom();
          if(idx % 4 === 0) screenShake(2 + Math.random()*3);
        });
      }));
    })(i);
  }
  // Sustained rumble — additional muzzle flashes
  for(var j=1; j<=3; j++) {
    (function(jj){
      promises.push(sleep((jj*600)/animSpeed).then(function(){
        if(ctx.cancelled) return;
        var muzzleJitter = [(Math.random()-.5)*0.01, (Math.random()-.5)*0.01];
        mkFlash([from[0]+muzzleJitter[0], from[1]+muzzleJitter[1]]).addTo(animLy);
      }));
    })(j);
  }
  return Promise.all(promises).then(function(){
    if(ctx.cancelled) return;
    screenShake(5);
    var endMsg = note || (isCounterBattery ? 'COUNTER-BATTERY COMPLETE' : 'FIRE MISSION COMPLETE');
    showMapLabel(to, endMsg, 'kill-label', 2500);
    return sleep(600/animSpeed);
  });
}

function animGround(ev, ctx) {
  if(ctx.cancelled) return Promise.resolve();
  var pos = [ev.lat, ev.lon];
  mkFlash(pos).addTo(animLy);
  sfx.explosion(false); screenShake(3);
  var hitText = ev.result.indexOf('victory')>=0 ? 'POSITION TAKEN' : ev.result.indexOf('defeat')>=0 ? 'REPULSED' : 'CONTESTED';
  showMapLabel(pos, hitText, ev.result.indexOf('victory')>=0?'kill-label':'engage-label', 2000);
  return sleep(1000/animSpeed);
}

// ── Drone swarm animation ──
function animDrone(ev, ctx) {
  var hasFlight = ev.from_lat != null && ev.lat != null &&
                  (ev.from_lat !== ev.lat || ev.from_lon !== ev.lon);
  var to = [ev.lat, ev.lon];
  var aName = fmtUnit(ev.attacker);
  var dName = fmtUnit(ev.defender);
  var note = evNote(ev);
  var isISR = (ev.phase||'').indexOf('isr') >= 0 || (note||'').toLowerCase().indexOf('isr') >= 0;
  var isSEAD = (ev.phase||'').indexOf('sead') >= 0 || (note||'').toLowerCase().indexOf('sead') >= 0;

  if(!hasFlight) {
    var swarm = mkDroneSwarm(to); swarm.addTo(animLy);
    sfx.droneBuzz();
    showMapLabel(to, aName + (isISR?' — ISR ORBIT':isSEAD?' — SEAD SWARM':' — DRONE STRIKE'), 'drone-label', 3000);
    return sleep(800/animSpeed).then(function(){
      if(ctx.cancelled) return;
      if(!isISR) {
        mkDroneStrikeFlash(to).addTo(animLy);
        sfx.explosion(false); screenShake(3);
        var hitText = ev.result.indexOf('victory')>=0 ? (note||'TARGET HIT') : ev.result.indexOf('defeat')>=0 ? 'DRONES INTERCEPTED' : 'PARTIAL EFFECT';
        showMapLabel(to, hitText, ev.result.indexOf('victory')>=0?'kill-label':'drone-label', 2500);
      } else {
        showMapLabel(to, 'INTEL GATHERED', 'drone-label', 2000);
      }
      return sleep(700/animSpeed);
    });
  }

  var from = [ev.from_lat, ev.from_lon];
  var droneColor = ev.attacker_faction === 'india' ? '#8866ff' : '#aa66ff';

  showMapLabel(from, aName + (isSEAD?' SEAD SWARM LAUNCHED':isISR?' ISR LAUNCH':' DRONE STRIKE'), 'drone-label', 2500);
  sfx.droneBuzz();

  var promises = [];
  var numDrones = isSEAD ? 5 : 3;
  for(var i=0;i<numDrones;i++){
    (function(idx){
      var jFrom = [from[0]+(Math.random()-.5)*.02, from[1]+(Math.random()-.5)*.02];
      var jTo = [to[0]+(Math.random()-.5)*.03, to[1]+(Math.random()-.5)*.03];
      promises.push(sleep((idx*150)/animSpeed).then(function(){
        if(ctx.cancelled) return;
        return flyObject(jFrom, jTo, {
          duration: 1400+idx*100, trailColor:droneColor, trailWeight:1,
          trailDash:'2,4', trailOpacity:.4,
          headColor:droneColor, headFill:droneColor, headRadius:2
        }, ctx);
      }));
    })(i);
  }

  return Promise.all(promises).then(function(){
    if(ctx.cancelled) return;
    if(isISR) {
      var swarm = mkDroneSwarm(to); swarm.addTo(animLy);
      showMapLabel(to, 'AREA SCANNED — '+aName, 'drone-label', 2500);
      return sleep(800/animSpeed);
    }
    var impacts = isSEAD ? 4 : 2;
    var impactPromises = [];
    for(var j=0;j<impacts;j++){
      (function(jj){
        impactPromises.push(sleep((jj*120)/animSpeed).then(function(){
          if(ctx.cancelled) return;
          var jitter = [(Math.random()-.5)*.02, (Math.random()-.5)*.02];
          var impactPt = [to[0]+jitter[0], to[1]+jitter[1]];
          mkDroneStrikeFlash(impactPt).addTo(animLy);
          if(jj===0) sfx.explosion(false);
        }));
      })(j);
    }
    return Promise.all(impactPromises).then(function(){
      if(ctx.cancelled) return;
      screenShake(isSEAD ? 5 : 3);
      var hitText = ev.result.indexOf('victory')>=0 ? (isSEAD?'SAM DESTROYED':'TARGET HIT') :
                    ev.result.indexOf('defeat')>=0 ? 'SWARM INTERCEPTED' : 'PARTIAL DAMAGE';
      showMapLabel(to, hitText, ev.result.indexOf('victory')>=0?'kill-label':'drone-label', 3000);
      return sleep(700/animSpeed);
    });
  });
}

// ── Helicopter animation ──
function animHeli(ev, ctx) {
  var hasFlight = ev.from_lat != null && ev.lat != null &&
                  (ev.from_lat !== ev.lat || ev.from_lon !== ev.lon);
  var to = [ev.lat, ev.lon];
  var aName = fmtUnit(ev.attacker);
  var dName = fmtUnit(ev.defender);
  var note = evNote(ev);
  var isAirAssault = (ev.phase||'').indexOf('air_assault') >= 0 || (note||'').toLowerCase().indexOf('air assault') >= 0 || (note||'').toLowerCase().indexOf('lz') >= 0;
  var fColor = ev.attacker_faction === 'india' ? '#44ccaa' : '#66ccaa';

  if(!hasFlight) {
    sfx.heliRotor();
    mkFlash(to).addTo(animLy);
    showMapLabel(to, aName + (isAirAssault?' — TROOPS INSERTED':' — ATTACK RUN'), 'heli-label', 2500);
    screenShake(3);
    return sleep(1000/animSpeed);
  }

  var from = [ev.from_lat, ev.from_lon];

  showMapLabel(from, aName + (isAirAssault?' AIR ASSAULT':' ATTACK MISSION'), 'heli-label', 2500);
  sfx.heliRotor();

  var mid1 = [lerp(from[0],to[0],0.33)+(Math.random()-.5)*.04,
              lerp(from[1],to[1],0.33)+(Math.random()-.5)*.04];
  var mid2 = [lerp(from[0],to[0],0.66)+(Math.random()-.5)*.04,
              lerp(from[1],to[1],0.66)+(Math.random()-.5)*.04];

  return flyObject(from, mid1, {
    duration:800, trailColor:fColor, trailWeight:1.5,
    trailDash:'4,3', trailOpacity:.5, plane:true, planeSize:14
  }, ctx).then(function(){
    if(ctx.cancelled) return;
    return flyObject(mid1, mid2, {
      duration:600, trailColor:fColor, trailWeight:1.5,
      trailDash:'4,3', trailOpacity:.4, plane:true, planeSize:14
    }, ctx);
  }).then(function(){
    if(ctx.cancelled) return;
    return flyObject(mid2, to, {
      duration:800, trailColor:fColor, trailWeight:1.5,
      trailDash:'4,3', trailOpacity:.5, plane:true, planeSize:14
    }, ctx);
  }).then(function(){
    if(ctx.cancelled) return;
    if(isAirAssault) {
      var lzRing = L.circleMarker(to, {
        radius:15, color:fColor, weight:2, fillColor:fColor,
        fillOpacity:0.15, dashArray:'6,4'
      }).addTo(animLy);
      showMapLabel(to, 'LZ — TROOPS DEPLOYING', 'heli-label', 3000);
      return sleep(800/animSpeed).then(function(){
        if(ctx.cancelled) return;
        var resultText = ev.result.indexOf('victory')>=0 ? (note||'INSERTION COMPLETE') :
                         ev.result.indexOf('defeat')>=0 ? 'LZ HOT — HEAVY LOSSES' : 'PARTIAL INSERTION';
        showMapLabel(to, resultText, ev.result.indexOf('victory')>=0?'kill-label':'heli-label', 2500);
        sfx.heliRotor();
        return flyObject(to, from, {
          duration:1200, trailColor:fColor, trailWeight:1,
          trailDash:'3,6', trailOpacity:.2, plane:true, planeSize:11, planeOpacity:.4
        }, ctx);
      });
    } else {
      showMapLabel(to, 'ENGAGING — '+dName, 'heli-label', 2000);
      sfx.missileLaunch();
      var strafes = [];
      for(var i=0;i<3;i++){
        (function(idx){
          strafes.push(sleep((idx*200)/animSpeed).then(function(){
            if(ctx.cancelled) return;
            var jit = [(Math.random()-.5)*.015, (Math.random()-.5)*.015];
            mkHeliStrikeFlash([to[0]+jit[0],to[1]+jit[1]]).addTo(animLy);
            if(idx===0) sfx.explosion(false);
          }));
        })(i);
      }
      return Promise.all(strafes).then(function(){
        if(ctx.cancelled) return;
        screenShake(4);
        var hitText = ev.result.indexOf('victory')>=0 ? (note||'TARGET DESTROYED — '+dName) :
                      ev.result.indexOf('defeat')>=0 ? 'SHOT DOWN' : 'ENGAGED — '+dName;
        showMapLabel(to, hitText, ev.result.indexOf('victory')>=0?'kill-label':'heli-label', 3000);
        sfx.heliRotor();
        return flyObject(to, from, {
          duration:1200, trailColor:fColor, trailWeight:1,
          trailDash:'3,6', trailOpacity:.2, plane:true, planeSize:11, planeOpacity:.4
        }, ctx);
      });
    }
  });
}

// ── Special Forces animation ──
function animSF(ev, ctx) {
  if(ctx.cancelled) return Promise.resolve();
  var to = [ev.lat, ev.lon];
  var aName = fmtUnit(ev.attacker);
  var dName = fmtUnit(ev.defender);
  var note = evNote(ev);
  var isRecon = (ev.phase||'').indexOf('recon') >= 0 || (note||'').toLowerCase().indexOf('recon') >= 0 ||
                (note||'').toLowerCase().indexOf('sr') >= 0;
  var isRaid = (note||'').toLowerCase().indexOf('raid') >= 0 || (note||'').toLowerCase().indexOf('da') >= 0;
  var isSabotage = (note||'').toLowerCase().indexOf('sabotage') >= 0;

  var hasFlight = ev.from_lat != null && ev.lat != null &&
                  (ev.from_lat !== ev.lat || ev.from_lon !== ev.lon);

  if(hasFlight) {
    var from = [ev.from_lat, ev.from_lon];
    showMapLabel(from, aName + ' — INFILTRATING', 'sf-label', 2500);
    return flyObject(from, to, {
      duration:2000, trailColor:'#cc88ff', trailWeight:1,
      trailDash:'2,8', trailOpacity:.25,
      headColor:'#cc88ff', headFill:'#cc88ff', headRadius:2
    }, ctx).then(function(){
      if(ctx.cancelled) return;
      return sfPhase2(ev, ctx, to, aName, dName, note, isRecon, isRaid, isSabotage);
    });
  } else {
    return sfPhase2(ev, ctx, to, aName, dName, note, isRecon, isRaid, isSabotage);
  }
}

function sfPhase2(ev, ctx, to, aName, dName, note, isRecon, isRaid, isSabotage) {
  if(ctx.cancelled) return Promise.resolve();

  if(isRecon) {
    mkSFPing(to).addTo(animLy);
    showMapLabel(to, aName + ' — EYES ON TARGET', 'sf-label', 2500);
    return sleep(600/animSpeed).then(function(){
      if(ctx.cancelled) return;
      return sleep(500/animSpeed);
    }).then(function(){
      if(ctx.cancelled) return;
      mkSFPing(to).addTo(animLy);
      var resultText = ev.result.indexOf('victory')>=0 ? 'INTEL SECURED' :
                       ev.result.indexOf('defeat')>=0 ? 'COMPROMISED' : 'PARTIAL INTEL';
      showMapLabel(to, resultText, ev.result.indexOf('victory')>=0?'kill-label':'sf-label', 2500);
      return sleep(600/animSpeed);
    });
  }

  if(isSabotage) {
    mkSFPing(to).addTo(animLy);
    showMapLabel(to, aName + ' — CHARGES SET', 'sf-label', 2000);
    return sleep(900/animSpeed).then(function(){
      if(ctx.cancelled) return;
      mkExplosion(to, false).addTo(animLy);
      sfx.explosion(true); screenShake(6);
      var resultText = ev.result.indexOf('victory')>=0 ? (note||'OBJECTIVE DESTROYED') :
                       ev.result.indexOf('defeat')>=0 ? 'SABOTAGE FAILED' : 'PARTIAL DAMAGE';
      showMapLabel(to, resultText, ev.result.indexOf('victory')>=0?'kill-label':'sf-label', 3000);
      return sleep(700/animSpeed);
    });
  }

  // Raid / DA — suppressed fire then assault
  sfx.sfSilenced();
  mkSFPing(to).addTo(animLy);
  showMapLabel(to, aName + ' — CONTACT', 'sf-label', 2000);
  return sleep(500/animSpeed).then(function(){
    if(ctx.cancelled) return;
    var shots = [];
    for(var i=0;i<4;i++){
      (function(idx){
        shots.push(sleep((idx*180)/animSpeed).then(function(){
          if(ctx.cancelled) return;
          var jit = [(Math.random()-.5)*.01, (Math.random()-.5)*.01];
          mkFlash([to[0]+jit[0],to[1]+jit[1]]).addTo(animLy);
          if(idx===2) sfx.sfSilenced();
        }));
      })(i);
    }
    return Promise.all(shots);
  }).then(function(){
    if(ctx.cancelled) return;
    screenShake(3);
    var resultText = ev.result.indexOf('victory')>=0 ? (note||'RAID SUCCESS — '+dName) :
                     ev.result.indexOf('defeat')>=0 ? 'TEAM COMPROMISED' : 'PARTIAL SUCCESS';
    var compromised = (note||'').toLowerCase().indexOf('compromised') >= 0;
    if(compromised) resultText = 'COMPROMISED — FIGHTING EXTRACTION';
    showMapLabel(to, resultText, ev.result.indexOf('victory')>=0?'kill-label':'sf-label', 3000);
    return sleep(700/animSpeed);
  });
}

function animEvent(ev, ctx) {
  var hasFlight = ev.from_lat != null && ev.lat != null &&
                  (ev.from_lat !== ev.lat || ev.from_lon !== ev.lon);
  var pd = phaseFor(ev);
  if(pd.type==='missile') return animMissile(ev, ctx);
  if(pd.type==='air') return animAir(ev, ctx);
  if(pd.type==='drone') return animDrone(ev, ctx);
  if(pd.type==='arty') return animArty(ev, ctx);
  if(pd.type==='heli') return animHeli(ev, ctx);
  if(pd.type==='sf') return animSF(ev, ctx);
  return animGround(ev, ctx);
}

// ── Orchestrate turn animation ──
async function animateTurn(turnIndex) {
  cancelAnim();
  var ctx = {cancelled:false};
  currentAnim = ctx;
  var t = D.turns[turnIndex]; if(!t) return;

  // Show previous turn's units as backdrop
  var prevIdx = turnIndex > 0 ? turnIndex - 1 : 0;
  turn = prevIdx;
  showTurn(prevIdx);

  // Prepare battle feed for this turn
  feedClear();
  feedLine('TURN '+t.turn+' \u2014 DAY '+t.day+' '+t.time.toUpperCase()+' \u2014 '+cap(t.weather), 'fc-dim');
  feedSeparator();
  await sleep(300/animSpeed);
  if(ctx.cancelled) return;

  // Add reasoning to feeds
  feedReasoning(t);

  var events = t.combat_events||[];
  if(events.length === 0) {
    feedLine('No combat this turn \u2014 forces holding position', 'fc-dim');
    await sleep(400/animSpeed);
    if(ctx.cancelled) return;
    showTurn(turnIndex); turn = turnIndex;
    return;
  }

  // Group events by phase definition
  var groups = [];
  var used = new Array(events.length);
  for(var pi=0; pi<PHASE_DEFS.length; pi++) {
    var pd = PHASE_DEFS[pi];
    var grp = [];
    for(var ei=0; ei<events.length; ei++) {
      if(used[ei]) continue;
      if(pd.match.test(events[ei].phase)) { grp.push(events[ei]); used[ei]=true; }
    }
    if(grp.length>0) groups.push({def:pd, events:grp});
  }

  // Animate each phase group with battle feed
  for(var gi=0; gi<groups.length; gi++) {
    if(ctx.cancelled) return;
    var g = groups[gi];

    // Phase header in feed + overlay
    feedPhaseHeader(g.def.label, g.def.color);
    showPhaseLabel(g.def.label, g.def.color);
    await sleep(500/animSpeed);
    if(ctx.cancelled) return;

    // Stream opening feed lines for all events in this phase
    var allFeedData = g.events.map(function(ev){ return eventToFeedLines(ev); });
    for(var fi=0; fi<allFeedData.length; fi++) {
      if(ctx.cancelled) return;
      await streamFeedLines(allFeedData[fi].opening, ctx, 60);
      if(fi < allFeedData.length-1) await sleep(80/animSpeed);
    }
    await sleep(200/animSpeed);
    if(ctx.cancelled) return;

    // Animate all events on map simultaneously
    var promises = g.events.map(function(ev){ return animEvent(ev, ctx); });
    await Promise.all(promises);
    if(ctx.cancelled) return;

    // Show floating combat text for each event result
    g.events.forEach(function(ev){ resultFloatText(ev); });

    // Stream result lines after animations complete
    for(var ri=0; ri<allFeedData.length; ri++) {
      if(ctx.cancelled) return;
      await streamFeedLines(allFeedData[ri].closing, ctx, 80);
    }

    feedSeparator();
    await sleep(500/animSpeed);
    animLy.clearLayers();
    hidePhaseLabel();
  }

  if(ctx.cancelled) return;
  // Show final state
  showTurn(turnIndex);
  turn = turnIndex;
}

// ── Playback controls ──
async function playLoop() {
  while(playing && turn < D.turns.length-1) {
    await animateTurn(turn+1);
    if(!playing) break;
    await sleep(600/animSpeed);
  }
  if(turn >= D.turns.length-1) {
    playing = false;
    document.getElementById('play-btn').innerHTML = '&#9654;';
  }
}

function togglePlay() {
  playing = !playing;
  document.getElementById('play-btn').innerHTML = playing ? '&#9646;&#9646;' : '&#9654;';
  if(playing) {
    playLoop();
  } else {
    cancelAnim();
  }
}

function manualGo(i) {
  if(playing) togglePlay();
  cancelAnim();
  showTurn(i);
  var t = D.turns[turn];
  if(t) feedTurnSummary(t);
}
function manualNext() { manualGo(Math.min(turn+1, D.turns.length-1)); }
function manualPrev() { manualGo(Math.max(turn-1, 0)); }

document.addEventListener('keydown', function(e) {
  if(e.key==='ArrowRight') manualNext();
  else if(e.key==='ArrowLeft') manualPrev();
  else if(e.key===' ') { e.preventDefault(); togglePlay(); }
});

// ── Helpers ──
function cap(s){return s?s.charAt(0).toUpperCase()+s.slice(1):'';}
function esc(s){var d=document.createElement('div');d.textContent=s||'';return d.innerHTML;}
function fmtKey(k){return k.replace(/_/g,' ').replace(/\b\w/g,function(c){return c.toUpperCase();});}

document.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>"""
