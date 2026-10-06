"""Derived match statistics; unavailable fields stay unavailable."""
from datetime import datetime


def ratio(a, b, digits=1):
    return round(a / b, digits) if a is not None and b else None


def match_stats(match, puuid):
    players = match.get("players") or []
    player = next((p for p in players if p.get("subject") == puuid), {})
    stats = player.get("stats") or {}
    own = next((t for t in match.get("teams", []) if t.get("teamId") == player.get("teamId")), {})
    enemy = next((t for t in match.get("teams", []) if t.get("teamId") != player.get("teamId")), {})
    result = None
    if own and enemy and "roundsWon" in own and "roundsWon" in enemy:
        result = "勝利" if own.get("won") else "平手" if own["roundsWon"] == enemy["roundsWon"] else "敗北"
    rounds = stats.get("roundsPlayed")
    data = {**stats, "result": result, "acs": ratio(stats.get("score"), rounds),
            "kd": ratio(stats.get("kills"), stats.get("deaths"), 2),
            "damage": None, "hits": None, "headshots": None, "adr": None, "hs": None,
            "first_kills": None, "first_deaths": None, "plants": None, "defuses": None,
            "multikills": None, "best_round": None, "spent": None}
    ranked = [p for p in players if ratio((p.get("stats") or {}).get("score"),
                                        (p.get("stats") or {}).get("roundsPlayed")) is not None]
    if data["acs"] is not None:
        data["position"] = 1 + sum(ratio(p["stats"]["score"], p["stats"]["roundsPlayed"]) > data["acs"]
                                   for p in ranked)
        data["player_count"] = len(ranked)
    results = match.get("roundResults") or []
    mine = [next((p for p in r.get("playerStats", []) if p.get("subject") == puuid), {}) for r in results]
    # Require round coverage: sparse responses must not appear as zero damage.
    complete = rounds and len(results) == rounds and all(mine)
    if complete and all("damage" in p for p in mine):
        damage = [d for p in mine for d in (p.get("damage") or [])]
        if all("damage" in d for d in damage):
            data["damage"] = sum(d["damage"] for d in damage)
            data["adr"] = ratio(data["damage"], rounds)
        if all(all(k in d for k in ("headshots", "bodyshots", "legshots")) for d in damage):
            data["headshots"] = sum(d["headshots"] for d in damage)
            data["hits"] = sum(d[k] for d in damage for k in ("headshots", "bodyshots", "legshots"))
            data["hs"] = ratio(data["headshots"] * 100, data["hits"])
    if complete:
        for field, key in (("plants", "bombPlanter"), ("defuses", "bombDefuser")):
            data[field] = sum(r.get(key) == puuid for r in results)
        if all("kills" in p for r in results for p in r.get("playerStats", [])) and all(
            all(k in kill for k in ("roundTime", "killer", "victim"))
            for r in results for p in r.get("playerStats", []) for kill in p.get("kills", [])):
            first_kills = first_deaths = 0
            for r in results:
                kills = [k for p in r.get("playerStats", []) for k in p.get("kills", [])]
                kills = [k for k in kills if isinstance(k.get("roundTime"), (int, float))]
                if kills:
                    first = min(kills, key=lambda k: k["roundTime"])
                    first_kills += first.get("killer") == puuid
                    first_deaths += first.get("victim") == puuid
            data["first_kills"], data["first_deaths"] = first_kills, first_deaths
        if all("kills" in p for p in mine):
            counts = [len(p.get("kills") or []) for p in mine]
            data["multikills"] = {i: counts.count(i) for i in range(2, 6)}
            data["best_round"] = max(counts, default=0)
        if all("spent" in (p.get("economy") or {}) for p in mine):
            data["spent"] = ratio(sum(p["economy"]["spent"] for p in mine), rounds)
    return data


def match_time(info):
    timestamp = info.get("gameStartMillis") or info.get("MatchStartTime")
    return datetime.fromtimestamp(timestamp / 1000).astimezone().strftime("%m/%d %H:%M") if timestamp else "時間未提供"


def recent_summary(matches, puuid):
    values = [match_stats(m, puuid) for m in matches]
    rounds = sum(x.get("roundsPlayed") or 0 for x in values)
    def weighted(total):
        return ratio(sum(x[total] for x in values), rounds) if rounds and all(
            x.get(total) is not None and x.get("roundsPlayed") for x in values) else None
    return {"count": len(values), "wins": sum(x["result"] == "勝利" for x in values),
            "losses": sum(x["result"] == "敗北" for x in values),
            "draws": sum(x["result"] == "平手" for x in values),
            "unknown": sum(x["result"] is None for x in values), "rounds": rounds,
            "kills": sum(x.get("kills") or 0 for x in values) if all(x.get("kills") is not None for x in values) else None,
            "deaths": sum(x.get("deaths") or 0 for x in values) if all(x.get("deaths") is not None for x in values) else None,
            "assists": sum(x.get("assists") or 0 for x in values) if all(x.get("assists") is not None for x in values) else None,
            "acs": weighted("score"), "adr": weighted("damage"),
            "hs": ratio(sum(x["headshots"] for x in values) * 100, sum(x["hits"] for x in values))
            if all(x["hits"] is not None for x in values) else None}
