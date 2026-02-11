"""Generate test replay with a coherent 4-day war narrative."""

import json, sys, math
sys.path.insert(0, ".")
from replay_export import HTML_TEMPLATE

def lerp(a, b, t):
    return a + (b - a) * t

# ==============================================================
# STATIC DATA — Theater of operations
# ==============================================================

sam_sites = [
    {"name": "S-400 Adampur", "faction": "india", "type": "S-400", "lat": 31.43, "lon": 75.76, "range_km": 380},
    {"name": "Akash Amritsar", "faction": "india", "type": "Akash", "lat": 31.63, "lon": 74.87, "range_km": 30},
    {"name": "SPYDER Bathinda", "faction": "india", "type": "SPYDER", "lat": 30.21, "lon": 74.95, "range_km": 18},
    {"name": "HQ-9 Sargodha", "faction": "pakistan", "type": "HQ-9", "lat": 32.08, "lon": 72.67, "range_km": 125},
    {"name": "LY-80 Multan", "faction": "pakistan", "type": "LY-80", "lat": 30.20, "lon": 71.47, "range_km": 40},
]

static = {
    "rivers": [
        {"name": "Indus", "path": [{"lat": 35.5, "lon": 74.0}, {"lat": 34.0, "lon": 72.5}, {"lat": 32.0, "lon": 71.5}, {"lat": 30.0, "lon": 71.0}, {"lat": 28.0, "lon": 68.5}], "width": 300},
        {"name": "Chenab", "path": [{"lat": 33.5, "lon": 75.5}, {"lat": 32.5, "lon": 74.5}, {"lat": 31.5, "lon": 73.5}, {"lat": 30.5, "lon": 72.5}], "width": 150},
        {"name": "Ravi", "path": [{"lat": 32.5, "lon": 75.4}, {"lat": 31.9, "lon": 74.9}, {"lat": 31.5, "lon": 74.4}, {"lat": 30.8, "lon": 73.8}], "width": 100},
        {"name": "Sutlej", "path": [{"lat": 31.5, "lon": 76.8}, {"lat": 31.0, "lon": 75.5}, {"lat": 30.5, "lon": 74.5}, {"lat": 29.5, "lon": 73.5}], "width": 120},
    ],
    "cities": [
        {"name": "New Delhi", "lat": 28.61, "lon": 77.21, "faction": "india", "population": 21e6, "type": "capital"},
        {"name": "Islamabad", "lat": 33.69, "lon": 73.04, "faction": "pakistan", "population": 2e6, "type": "capital"},
        {"name": "Lahore", "lat": 31.55, "lon": 74.35, "faction": "pakistan", "population": 11e6, "type": "major"},
        {"name": "Amritsar", "lat": 31.63, "lon": 74.87, "faction": "india", "population": 1.2e6, "type": "major"},
        {"name": "Multan", "lat": 30.20, "lon": 71.47, "faction": "pakistan", "population": 2e6, "type": "major"},
        {"name": "Rawalpindi", "lat": 33.60, "lon": 73.05, "faction": "pakistan", "population": 2.1e6, "type": "major"},
        {"name": "Faisalabad", "lat": 31.42, "lon": 73.08, "faction": "pakistan", "population": 3.2e6, "type": "major"},
        {"name": "Sialkot", "lat": 32.50, "lon": 74.53, "faction": "pakistan", "population": 0.6e6, "type": "minor"},
        {"name": "Ludhiana", "lat": 30.90, "lon": 75.86, "faction": "india", "population": 1.6e6, "type": "major"},
        {"name": "Jalandhar", "lat": 31.32, "lon": 75.58, "faction": "india", "population": 0.9e6, "type": "minor"},
    ],
    "airbases": [
        {"id": "ab_adampur", "name": "Adampur AB", "faction": "india", "lat": 31.43, "lon": 75.76},
        {"id": "ab_ambala", "name": "Ambala AB", "faction": "india", "lat": 30.38, "lon": 76.78},
        {"id": "ab_pathankot", "name": "Pathankot AB", "faction": "india", "lat": 32.23, "lon": 75.63},
        {"id": "ab_halwara", "name": "Halwara AB", "faction": "india", "lat": 30.74, "lon": 75.59},
        {"id": "ab_sargodha", "name": "Sargodha AB", "faction": "pakistan", "lat": 32.08, "lon": 72.67},
        {"id": "ab_rafiqui", "name": "Rafiqui AB", "faction": "pakistan", "lat": 30.77, "lon": 72.28},
        {"id": "ab_kamra", "name": "Kamra APC", "faction": "pakistan", "lat": 33.87, "lon": 72.40},
        {"id": "ab_mianwali", "name": "Mianwali AB", "faction": "pakistan", "lat": 32.56, "lon": 71.57},
    ],
    "sectors": [
        {"id": "punjab_n", "name": "Punjab North (Sialkot)", "terrain": "plains", "north": 33.0, "south": 31.8, "east": 75.5, "west": 73.5},
        {"id": "punjab_c", "name": "Punjab Central (Lahore)", "terrain": "plains", "north": 31.8, "south": 30.5, "east": 75.5, "west": 73.5},
    ],
    "loc_path": [
        {"lat": 32.90, "lon": 73.80}, {"lat": 32.50, "lon": 74.53},
        {"lat": 31.95, "lon": 74.63}, {"lat": 31.60, "lon": 74.57},
        {"lat": 31.10, "lon": 74.30}, {"lat": 30.20, "lon": 73.50},
    ],
    "choke_points": [
        {"name": "Wagah Border", "lat": 31.60, "lon": 74.57, "type": "border_crossing"},
        {"name": "Hussainiwala", "lat": 30.95, "lon": 74.10, "type": "border_crossing"},
    ],
    "sam_sites": sam_sites,
}

# ==============================================================
# UNITS — Start positions
# ==============================================================

units_t0 = [
    # INDIA — formations
    {"id": "in_2corps_hq", "name": "II Strike Corps HQ", "faction": "india", "category": "ground", "type": "corps_hq", "lat": 31.32, "lon": 75.58, "status": "active", "strength": 100, "posture": "offensive"},
    {"id": "in_21div", "name": "21 Armoured Division", "faction": "india", "category": "ground", "type": "armored_division", "lat": 31.50, "lon": 75.10, "status": "active", "strength": 95, "posture": "offensive"},
    {"id": "in_14div", "name": "14 Infantry Division", "faction": "india", "category": "ground", "type": "infantry_division", "lat": 31.65, "lon": 74.95, "status": "active", "strength": 92, "posture": "offensive"},
    {"id": "in_arty_bde", "name": "Artillery Brigade", "faction": "india", "category": "artillery", "type": "artillery_brigade", "lat": 31.55, "lon": 74.80, "status": "active", "strength": 100, "posture": "offensive"},
    # INDIA — air
    {"id": "in_rafale_sq", "name": "17 Sqn Golden Arrows (Rafale)", "faction": "india", "category": "aircraft", "type": "multirole", "lat": 30.38, "lon": 76.78, "status": "active", "strength": 100, "posture": "offensive"},
    {"id": "in_su30_sq", "name": "24 Sqn Hawks (Su-30MKI)", "faction": "india", "category": "aircraft", "type": "air_superiority", "lat": 31.43, "lon": 75.76, "status": "active", "strength": 100, "posture": "offensive"},
    {"id": "in_mig29_sq", "name": "28 Sqn First Supersonics (MiG-29)", "faction": "india", "category": "aircraft", "type": "fighter", "lat": 32.23, "lon": 75.63, "status": "active", "strength": 100, "posture": "offensive"},
    # INDIA — missiles
    {"id": "in_brahmos1", "name": "BrahMos-I Battery (861 Regt)", "faction": "india", "category": "missile", "type": "cruise_missile", "lat": 30.90, "lon": 76.50, "status": "active", "strength": 100, "posture": "offensive"},
    {"id": "in_brahmos2", "name": "BrahMos-II Battery (862 Regt)", "faction": "india", "category": "missile", "type": "cruise_missile", "lat": 31.50, "lon": 76.20, "status": "active", "strength": 100, "posture": "offensive"},
    # INDIA — drones
    {"id": "in_heron_tp", "name": "Heron TP UAV Sqn (ISR)", "faction": "india", "category": "drone", "type": "male_uav", "lat": 31.43, "lon": 75.76, "status": "active", "strength": 100, "posture": "offensive"},
    {"id": "in_harop", "name": "IAI Harop Loitering Munition Btty", "faction": "india", "category": "drone", "type": "loitering_munition", "lat": 30.38, "lon": 76.78, "status": "active", "strength": 100, "posture": "offensive"},
    {"id": "in_rustom2", "name": "TAPAS/Rustom-II MALE UAV", "faction": "india", "category": "drone", "type": "male_uav", "lat": 30.74, "lon": 75.59, "status": "active", "strength": 100, "posture": "offensive"},
    # PAKISTAN — formations
    {"id": "pk_1corps_hq", "name": "I Corps HQ Mangla", "faction": "pakistan", "category": "ground", "type": "corps_hq", "lat": 33.06, "lon": 73.64, "status": "active", "strength": 100, "posture": "defensive"},
    {"id": "pk_6armd", "name": "6 Armoured Division", "faction": "pakistan", "category": "ground", "type": "armored_division", "lat": 31.80, "lon": 74.20, "status": "active", "strength": 90, "posture": "defensive"},
    {"id": "pk_10div", "name": "10 Infantry Division", "faction": "pakistan", "category": "ground", "type": "infantry_division", "lat": 31.55, "lon": 74.00, "status": "active", "strength": 88, "posture": "defensive"},
    {"id": "pk_arty_bde", "name": "Pakistan Artillery Group", "faction": "pakistan", "category": "artillery", "type": "artillery_brigade", "lat": 31.60, "lon": 73.90, "status": "active", "strength": 95, "posture": "defensive"},
    # PAKISTAN — air
    {"id": "pk_jf17_sq", "name": "16 Sqn Black Panthers (JF-17)", "faction": "pakistan", "category": "aircraft", "type": "fighter", "lat": 32.08, "lon": 72.67, "status": "active", "strength": 100, "posture": "defensive"},
    {"id": "pk_f16_sq", "name": "9 Sqn Griffins (F-16)", "faction": "pakistan", "category": "aircraft", "type": "multirole", "lat": 30.77, "lon": 72.28, "status": "active", "strength": 100, "posture": "defensive"},
    {"id": "pk_mirage_sq", "name": "8 Sqn Haiders (Mirage-III)", "faction": "pakistan", "category": "aircraft", "type": "strike", "lat": 33.87, "lon": 72.40, "status": "active", "strength": 85, "posture": "offensive"},
    # PAKISTAN — missiles
    {"id": "pk_babur", "name": "Babur-1A GLCM Battery", "faction": "pakistan", "category": "missile", "type": "cruise_missile", "lat": 32.50, "lon": 72.00, "status": "active", "strength": 100, "posture": "offensive"},
    {"id": "pk_nasr", "name": "Nasr SRBM Battery", "faction": "pakistan", "category": "missile", "type": "tactical_missile", "lat": 31.80, "lon": 73.50, "status": "active", "strength": 100, "posture": "offensive"},
    # PAKISTAN — drones
    {"id": "pk_burraq", "name": "Burraq Armed UAV Flight", "faction": "pakistan", "category": "drone", "type": "armed_uav", "lat": 32.08, "lon": 72.67, "status": "active", "strength": 100, "posture": "defensive"},
]

# ==============================================================
# WAR NARRATIVE — 4 days, 16 turns
# ==============================================================

# Front line progression (Indian advance toward Lahore)
# Border at approx lon 74.5. Lahore at 74.35.
# Artillery moves forward with the advance.
BORDER_LON = 74.55
LAHORE_LON = 74.35

turn_scripts = [
    # ── Turn 0: Pre-war ──
    None,

    # ══════════════════════════════════════════════════════════════
    # DAY 1 — AIR SUPERIORITY & SEAD (NO GROUND MOVEMENT)
    # ══════════════════════════════════════════════════════════════

    # ── Turn 1: Dawn — OPENING SEAD STRIKE ──
    {
        "time": "dawn", "weather": "hazy",
        "narrative_india": "D-Day Dawn: Operation Vijay Phase 1 — SEAD. BrahMos batteries fire simultaneous salvos at Sargodha AB and Kamra APC. IAI Harop loitering munitions launched toward Pakistani air defense radars — their job is to hunt and kill every radar that lights up. Heron TP drones orbiting at 30,000ft over Pakistani Punjab providing real-time ISR. No ground movement — air superiority first.",
        "narrative_pakistan": "D-Day Dawn: ALARM — Multiple hypersonic contacts inbound. BrahMos impacts on Sargodha — runway cratered, 4 JF-17s destroyed on ground. HQ-9 battery illuminates radar to engage — immediately targeted by Indian Harop loitering munition. Radar destroyed. Kamra APC also hit. We are blind and burning.",
        "events": [
            {"phase": "missile_strike", "attacker": "in_brahmos1", "defender": "pk_jf17_sq", "attacker_faction": "india", "interceptable": False, "result": "victory",
             "lat": 32.08, "lon": 72.67, "from_lat": 30.90, "from_lon": 76.50,
             "notes": ["BrahMos-I strike on Sargodha AB — runway cratered, 4 JF-17s destroyed"]},
            {"phase": "missile_strike", "attacker": "in_brahmos2", "defender": "pk_mirage_sq", "attacker_faction": "india", "interceptable": False, "result": "victory",
             "lat": 33.87, "lon": 72.40, "from_lat": 31.50, "from_lon": 76.20,
             "notes": ["BrahMos-II strike on Kamra APC — production facility destroyed"]},
            {"phase": "drone_operations", "attacker": "in_harop", "defender": "pk_jf17_sq", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 32.10, "lon": 72.70, "from_lat": 30.38, "from_lon": 76.78,
             "notes": ["Harop loitering munition dives on HQ-9 radar at Sargodha — radar destroyed"]},
            {"phase": "drone_operations", "attacker": "in_heron_tp", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.60, "lon": 74.20, "from_lat": 31.43, "from_lon": 75.76,
             "notes": ["Heron TP deep ISR — mapping all Pakistani forward positions in real-time"]},
        ],
        "front_advance": 0.0,
    },

    # ── Turn 2: Morning — AIR SUPERIORITY BATTLE ──
    {
        "time": "morning", "weather": "clear",
        "narrative_india": "D1 Morning: IAF goes for the kill. Rafale with Meteor BVR sweeping Pakistani airspace — 2 JF-17s shot down fleeing Sargodha. Su-30MKI establishing CAP over entire Lahore sector. Pakistan retaliates with Babur cruise missile salvo at Adampur — S-400 tracks and intercepts all 3. Heron TP feeding real-time BDA to command. Harop orbiting over Mianwali hunting for any radar that turns on.",
        "narrative_pakistan": "D1 Morning: Lost 2 more JF-17s to Rafale Meteor — they're being shot down at 100km+ range. Babur salvo against Adampur — all 3 intercepted by S-400. Total failure. F-16s from Rafiqui scrambled but can't get within AMRAAM range before being picked off. Pakistani Burraq drone launched for ISR but it's too slow — detected and tracked immediately.",
        "events": [
            {"phase": "air_operations", "attacker": "in_rafale_sq", "defender": "pk_jf17_sq", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 32.30, "lon": 73.50, "from_lat": 30.38, "from_lon": 76.78,
             "notes": ["Rafale BARCAP — Meteor BVR downs 2 JF-17s fleeing Sargodha"]},
            {"phase": "air_operations", "attacker": "in_su30_sq", "defender": "pk_f16_sq", "attacker_faction": "india", "interceptable": True, "result": "stalemate",
             "lat": 31.50, "lon": 73.80, "from_lat": 31.43, "from_lon": 75.76,
             "notes": ["Su-30MKI sweep — F-16s disengage before engagement, Indian air dominance"]},
            {"phase": "missile_strike", "attacker": "pk_babur", "defender": "in_su30_sq", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 31.43, "lon": 75.76, "from_lat": 32.50, "from_lon": 72.00,
             "notes": ["Babur salvo targeting Adampur AB — all 3 intercepted by S-400"]},
            {"phase": "drone_operations", "attacker": "in_harop", "defender": "pk_f16_sq", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 32.56, "lon": 71.60, "from_lat": 30.38, "from_lon": 76.78,
             "notes": ["Harop loitering over Mianwali — destroys LY-80 radar when it illuminates"]},
            {"phase": "drone_operations", "attacker": "pk_burraq", "defender": "in_21div", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 31.50, "lon": 75.00, "from_lat": 32.08, "from_lon": 72.67,
             "notes": ["Burraq ISR attempt — detected by Indian AWACS, shot down by MiG-29"]},
        ],
        "front_advance": 0.0,
    },

    # ── Turn 3: Afternoon — SEAD COMPLETE + AIR SUPREMACY ──
    {
        "time": "afternoon", "weather": "clear",
        "narrative_india": "D1 Afternoon: SEAD nearly complete. BrahMos-I strikes Rafiqui AB — last major PAF base in Punjab. Rafale downs 3 more JF-17s. Heron TP and Rustom-II drones now orbiting freely over Pakistani territory with zero opposition — feeding target coordinates to artillery planners. Air supremacy achieved. Ground forces ordered to prepare — H-Hour tonight.",
        "narrative_pakistan": "D1 Afternoon: Rafiqui AB destroyed by BrahMos. 3 more JF-17s lost — we cannot contest the sky. Indian drones flying freely over our positions — Heron TP at 30,000ft, we can't even reach them. They can see everything. F-16 squadron ordered to preserve remaining aircraft — they're all we have left. PAF effectively grounded in Punjab sector.",
        "events": [
            {"phase": "missile_strike", "attacker": "in_brahmos1", "defender": "pk_f16_sq", "attacker_faction": "india", "interceptable": False, "result": "victory",
             "lat": 30.77, "lon": 72.28, "from_lat": 30.90, "from_lon": 76.50,
             "notes": ["BrahMos-I strike on Rafiqui AB — F-16 hardened shelters penetrated"]},
            {"phase": "air_operations", "attacker": "in_rafale_sq", "defender": "pk_jf17_sq", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.80, "lon": 73.50, "from_lat": 30.38, "from_lon": 76.78,
             "notes": ["Rafale Meteor BVR — 3 JF-17s shot down. PAF JF-17 fleet combat ineffective."]},
            {"phase": "air_operations", "attacker": "pk_f16_sq", "defender": "in_su30_sq", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 31.55, "lon": 74.50, "from_lat": 30.77, "from_lon": 72.28,
             "notes": ["F-16 counter-air — 1 F-16 lost to Su-30MKI, survivors ordered to preserve fleet"]},
            {"phase": "drone_operations", "attacker": "in_heron_tp", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.55, "lon": 74.10, "from_lat": 31.43, "from_lon": 75.76,
             "notes": ["Heron TP mapping all 10 Div bunker positions — target list for artillery"]},
            {"phase": "drone_operations", "attacker": "in_rustom2", "defender": "pk_arty_bde", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.58, "lon": 73.92, "from_lat": 30.74, "from_lon": 75.59,
             "notes": ["Rustom-II locates Pakistani artillery group positions — coordinates passed to WLR"]},
        ],
        "front_advance": 0.0,
    },

    # ── Turn 4: Night — PREP BOMBARDMENT BEGINS ──
    {
        "time": "night", "weather": "clear",
        "narrative_india": "D1 Night: Air superiority confirmed. Now Phase 2: prep bombardment. Artillery Brigade opens up with everything — 155mm Dhanush, Pinaka MBRL, Smerch. Drone-fed coordinates mean every round is on target. 800+ rounds/hour sustained rate. Pakistani counter-battery attempt answered with 10x response — 3 gun positions wiped in first exchange. Heron TP providing real-time BDA of impacts.",
        "narrative_pakistan": "D1 Night: HELL ON EARTH. Indian artillery opened up using drone-fed coordinates — every round hits something. Non-stop. Our artillery fires back — Indian WLR has us in 5 minutes. They respond with 10x the firepower. 3 gun positions destroyed in first exchange. Indian drones circling overhead watching us burn. We can't move, can't shoot back, can't hide.",
        "events": [
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.58, "lon": 74.40, "from_lat": 31.60, "from_lon": 74.65,
             "notes": ["155mm Dhanush barrage on drone-located 10 Div positions — 3 bunkers destroyed"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.52, "lon": 74.38, "from_lat": 31.56, "from_lon": 74.62,
             "notes": ["Pinaka MBRL saturation fire on forward defenses — drone confirms direct hits"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.55, "lon": 74.42, "from_lat": 31.58, "from_lon": 74.63,
             "notes": ["Smerch heavy rockets pounding trench lines — Heron TP calling corrections"]},
            {"phase": "artillery", "attacker": "pk_arty_bde", "defender": "in_arty_bde", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 31.60, "lon": 74.62, "from_lat": 31.55, "from_lon": 74.10,
             "notes": ["Pakistani counter-battery attempt — WLR + drone spots them in 5 minutes"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_arty_bde", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.55, "lon": 74.12, "from_lat": 31.59, "from_lon": 74.64,
             "notes": ["Counter-battery 10x annihilation — 3 Pakistani gun positions wiped out"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_arty_bde", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.53, "lon": 74.08, "from_lat": 31.57, "from_lon": 74.61,
             "notes": ["Pinaka follow-up on Pakistani arty — Heron TP confirms ammo dump secondary explosion"]},
            {"phase": "drone_operations", "attacker": "in_heron_tp", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.56, "lon": 74.35, "from_lat": 31.43, "from_lon": 75.76,
             "notes": ["Heron TP real-time BDA — guiding artillery corrections onto surviving positions"]},
        ],
        "front_advance": 0.0,
    },

    # ══════════════════════════════════════════════════════════════
    # DAY 2 — GROUND OFFENSIVE BEGINS (Air superiority secured)
    # ══════════════════════════════════════════════════════════════

    # ── Turn 5: Dawn — BORDER CROSSING ──
    {
        "time": "dawn", "weather": "hazy",
        "narrative_india": "D2 Dawn: H-Hour. Air superiority secured, artillery pounding for 8 hours straight. 21 Armoured Div crosses at Wagah under rolling barrage. Bhairav Battalions air assault via Mi-17 to seize road junctions 15km ahead. Apache attack helicopters providing CAS against Pakistani armor. Para SF teams already behind enemy lines — recon confirms Lahore defenses. Harop loitering munitions orbit ahead. Nasr intercepted by S-400.",
        "narrative_pakistan": "D2 Dawn: Indian armor crossing at Wagah! Bhairav commandos inserted by helicopter behind our lines — road junctions seized. Apache helicopters attacking our armor from behind ridgelines. Indian SF spotted near our artillery positions — they've been watching us. A Harop just dove on our battalion commander's APC. Nasr launch against crossing — intercepted by S-400. We are being watched, tracked, and destroyed from every direction.",
        "events": [
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.57, "lon": 74.45, "from_lat": 31.60, "from_lon": 74.63,
             "notes": ["Rolling barrage walking ahead of 21 Div — 8 hours continuous fire"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.60, "lon": 74.46, "from_lat": 31.62, "from_lon": 74.64,
             "notes": ["Pinaka MBRL box barrage clearing path — drone-corrected impacts"]},
            {"phase": "helicopter_air_assault", "attacker": "in_bhairav_bn", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.55, "lon": 74.35, "from_lat": 31.60, "from_lon": 75.00,
             "notes": ["Bhairav Bn air assault via Mi-17 — road junction seized 15km behind border, LZ secure"]},
            {"phase": "helicopter_attack", "attacker": "in_apache_sqn", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.63, "lon": 74.25, "from_lat": 31.55, "from_lon": 75.10,
             "notes": ["Apache anti-armor CAS — 4 T-80s destroyed with Hellfire from behind ridgeline"]},
            {"phase": "special_forces_recon", "attacker": "in_para_sf_01", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.54, "lon": 74.20, "from_lat": 31.60, "from_lon": 74.70,
             "notes": ["Para SF deep recon — 10 Div defensive positions mapped, coordinates to arty"]},
            {"phase": "artillery", "attacker": "pk_arty_bde", "defender": "in_21div", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 31.58, "lon": 74.52, "from_lat": 31.54, "from_lon": 74.05,
             "notes": ["Pakistani guns fire on crossing — Rustom-II spots muzzle flash"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_arty_bde", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.54, "lon": 74.05, "from_lat": 31.60, "from_lon": 74.62,
             "notes": ["Counter-battery 10x response — drone + WLR pinpoints, Smerch obliterates"]},
            {"phase": "drone_sead", "attacker": "in_harop", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.57, "lon": 74.42, "from_lat": 31.60, "from_lon": 74.65,
             "notes": ["Harop SEAD swarm dives on 10 Div SAM radar — air defense destroyed"]},
            {"phase": "missile_strike", "attacker": "pk_nasr", "defender": "in_21div", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 31.58, "lon": 74.52, "from_lat": 31.80, "from_lon": 73.50,
             "notes": ["Nasr SRBM at Indian armor at Wagah — intercepted by S-400"]},
            {"phase": "ground_combat", "attacker": "in_21div", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.58, "lon": 74.48, "from_lat": None, "from_lon": None,
             "notes": ["21 Div breaches border behind rolling barrage — T-90s push through"]},
            {"phase": "ground_combat", "attacker": "in_14div", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.62, "lon": 74.50, "from_lat": None, "from_lon": None,
             "notes": ["14 Div secures northern flank under drone surveillance"]},
        ],
        "front_advance": 0.05,
    },

    # ── Turn 6: Morning — EXPANDING BRIDGEHEAD ──
    {
        "time": "morning", "weather": "clear",
        "narrative_india": "D2 Morning: 21 Div 8km inside Pakistan. Artillery non-stop for 14 hours. Heron TP detects Pakistani arty displacement — last guns trying to move. Rustom-II tracks them, artillery destroys convoy in 3 minutes. 70% of Pakistani guns now destroyed. Drones hunting stragglers. Rafale CAS on retreating 10 Div — Hammer precision bombs. Complete combined arms dominance.",
        "narrative_pakistan": "D2 Morning: Tried to displace our last guns — Indian drones tracked the movement. 3 minutes later, artillery rounds landed on the convoy. 70% of our artillery gone. Indian drones are EVERYWHERE — Heron at high altitude, Harop at medium altitude hunting anything that moves. Their artillery never stopped. 10 Div retreating to BRB Canal under constant bombardment.",
        "events": [
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.56, "lon": 74.36, "from_lat": 31.58, "from_lon": 74.55,
             "notes": ["14-hour sustained barrage — shifting fire to BRB Canal defenses"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.54, "lon": 74.33, "from_lat": 31.57, "from_lon": 74.53,
             "notes": ["Pinaka MBRL plastering 10 Div retreat routes to BRB Canal"]},
            {"phase": "drone_operations", "attacker": "in_rustom2", "defender": "pk_arty_bde", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.52, "lon": 73.95, "from_lat": 30.74, "from_lon": 75.59,
             "notes": ["Rustom-II tracks Pakistani arty displacement — coordinates to guns"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_arty_bde", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.52, "lon": 73.95, "from_lat": 31.57, "from_lon": 74.52,
             "notes": ["Drone-guided counter-battery — destroying Pakistani guns while moving"]},
            {"phase": "drone_operations", "attacker": "in_harop", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.55, "lon": 74.30, "from_lat": 31.58, "from_lon": 74.55,
             "notes": ["Harop hunting retreating Pakistani vehicles — command truck destroyed"]},
            {"phase": "air_operations", "attacker": "in_rafale_sq", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.56, "lon": 74.38, "from_lat": 30.38, "from_lon": 76.78,
             "notes": ["Rafale CAS — Hammer precision bombs on retreating 10 Div columns"]},
            {"phase": "ground_combat", "attacker": "in_21div", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.56, "lon": 74.42, "from_lat": None, "from_lon": None,
             "notes": ["21 Div pushes through Wahga town behind rolling barrage"]},
        ],
        "front_advance": 0.15,
    },

    # ── Turn 7: Afternoon — COUNTER-ATTACK SMASHED ──
    {
        "time": "afternoon", "weather": "cloudy",
        "narrative_india": "D2 Afternoon: Heron TP detects 6 Armoured Div forming up for counter-attack. Artillery redirected BEFORE they move. Apache attack helicopters launch from forward FARP — Hellfire missiles shredding T-80s from 8km standoff. SSG team detected near our logistics base — neutralized by security platoon. Harop diving on command vehicles. Counter-attack destroyed before it began.",
        "narrative_pakistan": "D2 Afternoon: Counter-attack catastrophe. Indian drones spotted us forming up. Apache helicopters appeared from behind ridgelines — 6 T-80s destroyed before our tanks even saw them. SSG sabotage team at Indian logistics base compromised — team lost. Our counter-attack force destroyed. We have nothing left to attack with.",
        "events": [
            {"phase": "drone_isr", "attacker": "in_heron_tp", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.62, "lon": 74.18, "from_lat": 31.43, "from_lon": 75.76,
             "notes": ["Heron TP ISR detects 6 Armoured Div forming up — coordinates to artillery"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.60, "lon": 74.22, "from_lat": 31.57, "from_lon": 74.47,
             "notes": ["Artillery preemptive strike on forming-up area — T-80s hit before moving"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.58, "lon": 74.20, "from_lat": 31.56, "from_lon": 74.45,
             "notes": ["Pinaka saturating approach routes — 5 T-80s burning"]},
            {"phase": "helicopter_attack", "attacker": "in_apache_sqn", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.61, "lon": 74.19, "from_lat": 31.55, "from_lon": 74.45,
             "notes": ["Apache Hellfire attack — 6 T-80s destroyed from 8km standoff behind ridgeline"]},
            {"phase": "drone_operations", "attacker": "in_harop", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.59, "lon": 74.21, "from_lat": 31.57, "from_lon": 74.47,
             "notes": ["Harop dives on 6 Armoured Div command vehicle — CO killed"]},
            {"phase": "special_forces", "attacker": "pk_ssg_01", "defender": "in_arty_bde", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 31.57, "lon": 74.60, "from_lat": 31.50, "from_lon": 74.10,
             "notes": ["SSG sabotage raid on Indian ammo depot — team compromised, 4 KIA"]},
            {"phase": "ground_combat", "attacker": "pk_6armd", "defender": "in_21div", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 31.55, "lon": 74.35, "from_lat": None, "from_lon": None,
             "notes": ["6 Armoured Div counter-attack shattered — survivors retreat"]},
            {"phase": "air_operations", "attacker": "pk_mirage_sq", "defender": "in_mig29_sq", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 31.50, "lon": 74.60, "from_lat": 33.87, "from_lon": 72.40,
             "notes": ["Mirage-III CAS intercepted by MiG-29 — 2 Mirages shot down"]},
        ],
        "front_advance": 0.20,
    },

    # ── Turn 8: Night — SECOND BABUR SALVO + DRONE HUNTING ──
    {
        "time": "night", "weather": "clear",
        "narrative_india": "D2 Night: Pakistan desperate — second Babur salvo targeting Pathankot and Ambala. S-400 intercepts all 4. Retaliatory BrahMos on Mianwali AB. Rustom-II drones doing night ISR with IR sensors — Pakistani forces can't hide even at night. Harop loitering over known Pakistani positions — anything that generates heat signature gets a kamikaze drone.",
        "narrative_pakistan": "D2 Night: Second Babur salvo — ALL INTERCEPTED by S-400. We've fired 7 Babur missiles total with zero hits. Mianwali AB destroyed by BrahMos. Worst of all — Indian drones are flying at night with IR sensors. We can't move, can't reposition, can't even light a fire. Any heat source draws a Harop attack. We are being hunted like animals in the dark.",
        "events": [
            {"phase": "missile_strike", "attacker": "pk_babur", "defender": "in_mig29_sq", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 32.23, "lon": 75.63, "from_lat": 32.50, "from_lon": 72.00,
             "notes": ["Babur targeting Pathankot AB — intercepted by S-400 at 160km"]},
            {"phase": "missile_strike", "attacker": "pk_babur", "defender": "in_rafale_sq", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 30.38, "lon": 76.78, "from_lat": 32.50, "from_lon": 72.00,
             "notes": ["Babur targeting Ambala AB — intercepted by S-400 at 200km"]},
            {"phase": "missile_strike", "attacker": "in_brahmos2", "defender": "pk_jf17_sq", "attacker_faction": "india", "interceptable": False, "result": "victory",
             "lat": 32.56, "lon": 71.57, "from_lat": 31.50, "from_lon": 76.20,
             "notes": ["BrahMos-II strike on Mianwali AB — PAF dispersal base destroyed"]},
            {"phase": "drone_operations", "attacker": "in_rustom2", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.58, "lon": 74.15, "from_lat": 30.74, "from_lon": 75.59,
             "notes": ["Rustom-II night IR surveillance — tracking all Pakistani vehicle movements"]},
            {"phase": "drone_operations", "attacker": "in_harop", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.55, "lon": 74.18, "from_lat": 31.57, "from_lon": 74.48,
             "notes": ["Harop night hunting — destroys Pakistani fuel truck convoy using IR"]},
        ],
        "front_advance": 0.22,
    },

    # ══════════════════════════════════════════════════════════════
    # DAY 3 — EXPLOITATION (Combined arms + drones everywhere)
    # ══════════════════════════════════════════════════════════════

    # ── Turn 9: Dawn — BRB CANAL BREAKTHROUGH ──
    {
        "time": "dawn", "weather": "clear",
        "narrative_india": "D3 Dawn: 36 hours of non-stop artillery. Gun crews rotating in shifts. BRB Canal defensive line pulverized — Heron TP confirms zero active defensive positions remain. 21 Div breaks through the rubble. Harop and Rustom-II swarming ahead of advance. Pakistani artillery is SILENT — they have no guns left. Every Pakistani movement tracked by drone swarm overhead.",
        "narrative_pakistan": "D3 Dawn: BRB Canal line DESTROYED. 36 hours of artillery guided by drones. Not one square meter unobserved. Nasr battery makes desperate launch — intercepted by S-400 AGAIN. We have no artillery, no air force, no air defense, no missiles that can get through. Indian drones circling at multiple altitudes — we can't even retreat without being tracked and struck.",
        "events": [
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.55, "lon": 74.30, "from_lat": 31.57, "from_lon": 74.45,
             "notes": ["36-hour sustained barrage — BRB Canal defenses pulverized"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.53, "lon": 74.27, "from_lat": 31.56, "from_lon": 74.43,
             "notes": ["Pinaka saturation on retreating 6 Armoured columns"]},
            {"phase": "drone_operations", "attacker": "in_heron_tp", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.54, "lon": 74.28, "from_lat": 31.43, "from_lon": 75.76,
             "notes": ["Heron TP BDA — confirms zero active Pakistani positions at BRB Canal"]},
            {"phase": "drone_operations", "attacker": "in_harop", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.53, "lon": 74.22, "from_lat": 31.55, "from_lon": 74.40,
             "notes": ["Harop hunting fleeing Pakistani armor — dives on retreating T-80"]},
            {"phase": "missile_strike", "attacker": "pk_nasr", "defender": "in_21div", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 31.55, "lon": 74.40, "from_lat": 31.80, "from_lon": 73.50,
             "notes": ["Nasr SRBM at Indian armor crossing BRB Canal — intercepted by S-400"]},
            {"phase": "ground_combat", "attacker": "in_21div", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.55, "lon": 74.32, "from_lat": None, "from_lon": None,
             "notes": ["21 Div breaks through pulverized BRB Canal line"]},
            {"phase": "air_operations", "attacker": "in_su30_sq", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.53, "lon": 74.25, "from_lat": 31.43, "from_lon": 75.76,
             "notes": ["Su-30MKI CAS on retreating armor — 3 T-80s destroyed"]},
        ],
        "front_advance": 0.40,
    },

    # ── Turn 10: Morning — APPROACHING LAHORE ──
    {
        "time": "morning", "weather": "clear",
        "narrative_india": "D3 Morning: Lead tanks 5km from Lahore. BrahMos decapitation strike on I Corps HQ Mangla. Drones now providing live feed of Lahore defenses to every tank commander. Harop orbiting over Lahore cantonment — any vehicle that moves gets destroyed. Rafale downs last operational JF-17. Complete operational dominance.",
        "narrative_pakistan": "D3 Morning: Indian tanks at our doorstep. Mangla HQ hit by BrahMos — GOC wounded. Indian drones overhead watching every movement in Lahore. We can't even reposition a single APC without a Harop diving on it. Last JF-17 shot down. No aircraft, no missiles, no artillery, no drones. COAS considering ceasefire.",
        "events": [
            {"phase": "missile_strike", "attacker": "in_brahmos1", "defender": "pk_1corps_hq", "attacker_faction": "india", "interceptable": False, "result": "victory",
             "lat": 33.06, "lon": 73.64, "from_lat": 30.90, "from_lon": 76.50,
             "notes": ["BrahMos-I decapitation strike on I Corps HQ Mangla — C2 disrupted"]},
            {"phase": "drone_operations", "attacker": "in_heron_tp", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.55, "lon": 74.34, "from_lat": 31.43, "from_lon": 75.76,
             "notes": ["Heron TP live feed of Lahore defenses — every position mapped"]},
            {"phase": "drone_operations", "attacker": "in_harop", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.54, "lon": 74.30, "from_lat": 31.55, "from_lon": 74.38,
             "notes": ["Harop destroys Pakistani APC trying to reposition in Lahore cantonment"]},
            {"phase": "ground_combat", "attacker": "in_21div", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "stalemate",
             "lat": 31.54, "lon": 74.33, "from_lat": None, "from_lon": None,
             "notes": ["21 Div advance slows at Lahore cantonment — urban defense stiffens"]},
            {"phase": "air_operations", "attacker": "in_rafale_sq", "defender": "pk_jf17_sq", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.60, "lon": 73.80, "from_lat": 30.38, "from_lon": 76.78,
             "notes": ["Rafale downs last operational JF-17 — PAF has zero fighters in Punjab"]},
        ],
        "front_advance": 0.45,
    },

    # ── Turn 11: Afternoon — LAHORE SIEGE ──
    {
        "time": "afternoon", "weather": "cloudy",
        "narrative_india": "D3 Afternoon: Artillery pounding Lahore cantonment — 48 hours continuous. Excalibur precision rounds on HQ buildings, coordinates fed by Heron TP hovering overhead. Harop destroying any vehicle that moves. 14 Div flanking through Shahdara. Last Mirage sortie shot down. The entire battlefield is transparent to us through drone swarm.",
        "narrative_pakistan": "D3 Afternoon: Cantonment under non-stop bombardment — 48 hours. Indian drones hovering overhead directing every round. Harop kamikaze drones killing any vehicle that starts its engine. Last Mirage sortie shot down. We have ZERO aircraft, ZERO artillery, ZERO missiles, ZERO drones. Just infantry in rubble. 6 Armoured Div fighting for survival.",
        "events": [
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.54, "lon": 74.33, "from_lat": 31.56, "from_lon": 74.42,
             "notes": ["Excalibur precision rounds on 6 Armoured Div HQ — drone-guided, direct hit"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.55, "lon": 74.30, "from_lat": 31.57, "from_lon": 74.40,
             "notes": ["Pinaka clearing cantonment blocks — Heron TP directing each salvo"]},
            {"phase": "drone_operations", "attacker": "in_harop", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.53, "lon": 74.32, "from_lat": 31.55, "from_lon": 74.38,
             "notes": ["Harop destroys Pakistani tank that started its engine — IR detection"]},
            {"phase": "ground_combat", "attacker": "in_21div", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "stalemate",
             "lat": 31.54, "lon": 74.34, "from_lat": None, "from_lon": None,
             "notes": ["Street fighting in cantonment rubble — 6 Armoured Div holding"]},
            {"phase": "ground_combat", "attacker": "in_14div", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.62, "lon": 74.30, "from_lat": None, "from_lon": None,
             "notes": ["14 Div flanks through Shahdara — encircling Lahore from north"]},
            {"phase": "air_operations", "attacker": "pk_mirage_sq", "defender": "in_21div", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 31.55, "lon": 74.40, "from_lat": 33.87, "from_lon": 72.40,
             "notes": ["Last Mirage-III sortie — both aircraft shot down by SHORADS"]},
        ],
        "front_advance": 0.50,
    },

    # ── Turn 12: Night — LAHORE SURROUNDED ──
    {
        "time": "night", "weather": "clear",
        "narrative_india": "D3 Night: Lahore surrounded. 14 Div cuts GT Road. Last Babur salvo intercepted by S-400. Rustom-II night ISR confirms no reinforcements possible — every road and bridge monitored. Harop loitering over all approaches. Artillery maintaining fire through the night — never stops.",
        "narrative_pakistan": "D3 Night: Lahore surrounded. GT Road cut. Last Babur salvo — all intercepted. Missile inventory EXHAUSTED with zero hits on any Indian base. Indian drones monitoring every road out of the city at night with IR. Any vehicle moving is destroyed within minutes. COAS contacts Chinese embassy for ceasefire.",
        "events": [
            {"phase": "missile_strike", "attacker": "pk_babur", "defender": "in_su30_sq", "attacker_faction": "pakistan", "interceptable": True, "result": "defeat",
             "lat": 30.74, "lon": 75.59, "from_lat": 32.50, "from_lon": 72.00,
             "notes": ["Last Babur salvo at Halwara AB — intercepted. Missile inventory exhausted."]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.54, "lon": 74.32, "from_lat": 31.56, "from_lon": 74.40,
             "notes": ["Night bombardment continues — 48+ hours, gun crews rotating"]},
            {"phase": "drone_operations", "attacker": "in_rustom2", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.50, "lon": 74.20, "from_lat": 30.74, "from_lon": 75.59,
             "notes": ["Rustom-II night IR — confirms no reinforcements on any road to Lahore"]},
            {"phase": "ground_combat", "attacker": "in_14div", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.50, "lon": 74.20, "from_lat": None, "from_lon": None,
             "notes": ["14 Div cuts GT Road west of Lahore — city surrounded"]},
        ],
        "front_advance": 0.55,
    },

    # ══════════════════════════════════════════════════════════════
    # DAY 4 — ENDGAME
    # ══════════════════════════════════════════════════════════════

    # ── Turn 13: Dawn — CEASEFIRE TALKS + DEMONSTRATION STRIKE ──
    {
        "time": "dawn", "weather": "clear",
        "narrative_india": "D4 Dawn: Ceasefire negotiations via Chinese mediation. BrahMos demonstration strike on Multan Cantt — showing we can hit anywhere. Drones still orbiting over all of Pakistani Punjab. Artillery maintains fire on Lahore cantonment. International pressure building but India negotiating from total strength.",
        "narrative_pakistan": "D4 Dawn: Negotiating ceasefire. BrahMos just hit Multan Cantt — 400km from the front. They can strike anywhere, anytime. Their drones can see everything we do. We have no conventional answer. Accepting terms.",
        "events": [
            {"phase": "missile_strike", "attacker": "in_brahmos2", "defender": "pk_1corps_hq", "attacker_faction": "india", "interceptable": False, "result": "victory",
             "lat": 30.20, "lon": 71.47, "from_lat": 31.50, "from_lon": 76.20,
             "notes": ["BrahMos-II demonstration strike on Multan Cantt — showing strategic reach"]},
            {"phase": "artillery", "attacker": "in_arty_bde", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.54, "lon": 74.33, "from_lat": 31.56, "from_lon": 74.40,
             "notes": ["Artillery sustained fire on cantonment — maintaining pressure during talks"]},
            {"phase": "drone_operations", "attacker": "in_heron_tp", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.54, "lon": 74.33, "from_lat": 31.43, "from_lon": 75.76,
             "notes": ["Heron TP continuous surveillance — broadcasting live to negotiation room"]},
        ],
        "front_advance": 0.55,
    },

    # ── Turn 14: Morning — LAHORE FALLS ──
    {
        "time": "morning", "weather": "clear",
        "narrative_india": "D4 Morning: Final push. 21 Div enters cantonment from south, 14 Div from north. 6 Armoured Div commander surrenders with 23 remaining tanks. Lahore secured. Ceasefire effective 1400 hours. Indian drones provided total battlefield transparency — Pakistan couldn't move a single vehicle without being tracked.",
        "narrative_pakistan": "D4 Morning: 6 Armoured Div surrenders at Lahore. Lost our second largest city. PAF has 4 aircraft remaining in Punjab. Strategic missiles: zero. Artillery: zero. Drones: zero. Ceasefire signed. Complete military defeat — Indian drones, BrahMos, S-400, and relentless artillery were unstoppable.",
        "events": [
            {"phase": "ground_combat", "attacker": "in_21div", "defender": "pk_6armd", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.54, "lon": 74.34, "from_lat": None, "from_lon": None,
             "notes": ["21 Div enters Lahore cantonment — 6 Armoured Div surrenders, 23 tanks"]},
            {"phase": "ground_combat", "attacker": "in_14div", "defender": "pk_10div", "attacker_faction": "india", "interceptable": True, "result": "victory",
             "lat": 31.58, "lon": 74.32, "from_lat": None, "from_lon": None,
             "notes": ["14 Div secures northern Lahore — 10 Div remnants surrender"]},
        ],
        "front_advance": 0.60,
    },

    # ── Turn 15: Afternoon — CEASEFIRE ──
    {
        "time": "afternoon", "weather": "clear",
        "narrative_india": "D4 Afternoon: CEASEFIRE IN EFFECT. Indian forces hold Lahore. All ops suspended. S-400 on alert, drones maintaining surveillance. Victory — achieved through: (1) BrahMos SEAD destroying airbases, (2) Harop killing radars, (3) Rafale/Su-30 air supremacy, (4) Drone ISR providing total transparency, (5) Overwhelming artillery with drone-fed coordinates, (6) Ground advance only after air superiority confirmed.",
        "narrative_pakistan": "D4 Afternoon: Ceasefire. Indian forces in Lahore. Catastrophic defeat. Lessons: BrahMos unstoppable. S-400 negated all our missiles. Indian drones gave them godlike battlefield awareness. Their artillery — drone-guided, non-stop, 10x counter-battery — destroyed our gun line in 24 hours. We fought blind while they saw everything. Worst defeat since 1971.",
        "events": [],
        "front_advance": 0.60,
    },

    # ── Turn 16: Night — POST-CEASEFIRE ──
    {
        "time": "night", "weather": "clear",
        "narrative_india": "D4 Night: Post-ceasefire consolidation. Drones still orbiting — trust but verify. Total losses: 127 KIA, 340 wounded, 8 tanks, 0 aircraft, 3 drones. Pakistani losses: 2,400+ KIA, 180+ tanks/AFVs, 18 aircraft, 4 airbases, entire artillery arm, all strategic missiles expended with zero hits. Key enabler: drone swarm providing 24/7 real-time battlefield intelligence.",
        "narrative_pakistan": "D4 Night: Loss assessment — catastrophic. 2,400+ KIA. 6 Armoured Div and 10 Div destroyed. 18 aircraft lost. 4 airbases cratered by BrahMos. ALL Babur missiles intercepted by S-400. ALL Nasr missiles intercepted. Entire artillery force destroyed by drone-guided counter-battery. Indian drones made our battlefield completely transparent to them. We need our own S-400, our own BrahMos, and our own drone fleet. Without them, conventional war is suicide.",
        "events": [],
        "front_advance": 0.60,
    },
]

# ==============================================================
# BUILD TURNS
# ==============================================================

turns = []
i_vp, p_vp = 0, 0
current_units = [dict(u) for u in units_t0]

# Turn 0
turns.append({
    "turn": 0, "day": 1, "time": "pre-war", "weather": "clear",
    "india_vp": 0, "pakistan_vp": 0,
    "units": [dict(u) for u in current_units],
    "combat_events": [],
    "india_orders": {}, "pakistan_orders": {},
    "india_reasoning": "Pre-war deployment complete. II Strike Corps in forward assembly areas. S-400 batteries active. BrahMos regiments at launch positions. IAF on maximum readiness. Operation Vijay — H-Hour in 6 hours.",
    "pakistan_reasoning": "Intelligence suggests Indian mobilization along Punjab border. I Corps in defensive positions. 10 Div forward at Wagah sector. 6 Armoured Div in reserve near Lahore. PAF on standby. Babur batteries loaded. Hoping deterrence holds.",
})

for t in range(1, 17):
    script = turn_scripts[t]
    if script is None:
        continue

    day = (t - 1) // 4 + 1
    events = script.get("events", [])

    # Add default fields to events
    for e in events:
        e.setdefault("attacker_losses", {})
        e.setdefault("defender_losses", {})

    # Calculate VP
    for e in events:
        r = e.get("result", "")
        af = e.get("attacker_faction", "")
        phase = e.get("phase", "")
        # Victories score differently by type
        if r == "victory":
            if "missile" in phase:
                pts = 10  # strategic strikes worth more
            elif "ground" in phase:
                pts = 8   # territory gains
            elif "air" in phase:
                pts = 6   # air kills
            else:
                pts = 4   # arty
            if af == "india":
                i_vp += pts
            else:
                p_vp += pts
        elif r == "stalemate":
            # Defender gets credit for holding
            if af == "india":
                p_vp += 3  # Pak held against Indian attack
            else:
                i_vp += 3
        elif r == "defeat":
            # Attacker failed — defender gets points
            if af == "pakistan":
                i_vp += 5
            else:
                p_vp += 5

    # Update unit positions based on front advance
    adv = script.get("front_advance", 0)
    updated = []
    for u in current_units:
        u2 = dict(u)
        # Move Indian ground units forward
        if u2["faction"] == "india" and u2["category"] in ("ground", "artillery"):
            target_lon = lerp(u2["lon"], LAHORE_LON, adv)
            if target_lon < u2["lon"]:
                u2["lon"] = round(target_lon, 2)
        # Move Pakistani ground units back as they retreat
        if u2["faction"] == "pakistan" and u2["category"] in ("ground", "artillery"):
            retreat = max(0, adv - 0.1) * 0.3
            u2["lon"] = round(u2["lon"] - retreat, 2)
        updated.append(u2)
    current_units = updated

    # Count orders
    india_orders = {
        "missile_strikes": sum(1 for e in events if "missile" in e["phase"] and e.get("attacker_faction") == "india"),
        "air_missions": sum(1 for e in events if "air" in e["phase"] and "helicopter" not in e["phase"] and e.get("attacker_faction") == "india"),
        "drone_missions": sum(1 for e in events if "drone" in e["phase"] and e.get("attacker_faction") == "india"),
        "artillery_missions": sum(1 for e in events if "artil" in e["phase"] and e.get("attacker_faction") == "india"),
        "helicopter_missions": sum(1 for e in events if "helicopter" in e["phase"] and e.get("attacker_faction") == "india"),
        "ground_orders": sum(1 for e in events if "ground" in e["phase"] and e.get("attacker_faction") == "india"),
        "sf_missions": sum(1 for e in events if "special" in e["phase"] and e.get("attacker_faction") == "india"),
    }
    pakistan_orders = {
        "missile_strikes": sum(1 for e in events if "missile" in e["phase"] and e.get("attacker_faction") == "pakistan"),
        "air_missions": sum(1 for e in events if "air" in e["phase"] and "helicopter" not in e["phase"] and e.get("attacker_faction") == "pakistan"),
        "drone_missions": sum(1 for e in events if "drone" in e["phase"] and e.get("attacker_faction") == "pakistan"),
        "artillery_missions": sum(1 for e in events if "artil" in e["phase"] and e.get("attacker_faction") == "pakistan"),
        "helicopter_missions": sum(1 for e in events if "helicopter" in e["phase"] and e.get("attacker_faction") == "pakistan"),
        "ground_orders": sum(1 for e in events if "ground" in e["phase"] and e.get("attacker_faction") == "pakistan"),
        "sf_missions": sum(1 for e in events if "special" in e["phase"] and e.get("attacker_faction") == "pakistan"),
    }

    turns.append({
        "turn": t, "day": day,
        "time": script["time"],
        "weather": script["weather"],
        "india_vp": i_vp, "pakistan_vp": p_vp,
        "units": [dict(u) for u in current_units],
        "combat_events": events,
        "india_orders": india_orders,
        "pakistan_orders": pakistan_orders,
        "india_reasoning": script["narrative_india"],
        "pakistan_reasoning": script["narrative_pakistan"],
    })

# ==============================================================
# GENERATE HTML
# ==============================================================

replay_data = {
    "scenario": "hot_start_4day",
    "generated": "2026-02-11",
    "max_turns": 16,
    "static": static,
    "turns": turns,
}

json_str = json.dumps(replay_data, default=str).replace("</", "<\\/")
html = HTML_TEMPLATE.replace("/*__REPLAY_DATA__*/", json_str)

with open("test_replay.html", "w") as f:
    f.write(html)

print(f"Generated test_replay.html ({len(html) // 1024} KB)")
print(f"Turns: {len(turns)}")
print(f"Final VP — India: {i_vp}, Pakistan: {p_vp}")
print()
for t in turns[1:]:
    missile_count = sum(1 for e in t["combat_events"] if "missile" in e["phase"])
    air_count = sum(1 for e in t["combat_events"] if "air" in e["phase"] and "helicopter" not in e["phase"])
    drone_count = sum(1 for e in t["combat_events"] if "drone" in e["phase"])
    arty_count = sum(1 for e in t["combat_events"] if "artil" in e["phase"])
    heli_count = sum(1 for e in t["combat_events"] if "helicopter" in e["phase"])
    ground_count = sum(1 for e in t["combat_events"] if "ground" in e["phase"])
    sf_count = sum(1 for e in t["combat_events"] if "special" in e["phase"])
    print(f"  Turn {t['turn']:2d} Day {t['day']} {t['time']:10s} | M:{missile_count} A:{air_count} D:{drone_count} Art:{arty_count} H:{heli_count} G:{ground_count} SF:{sf_count}")
