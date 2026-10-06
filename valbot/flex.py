from __future__ import annotations

import json
from .analysis import match_stats, match_time, recent_summary

BG = "#101923"
PANEL = "#1B2935"
WHITE = "#F1F5F9"
MUTED = "#A5B4C3"
RED = "#FF4655"
GREEN = "#52D8A0"


def text(value, size="md", color=WHITE, **kwargs):
    return {"type": "text", "text": str(value)[:2000] or "—", "size": size,
            "color": color, "wrap": True, **kwargs}


def box(contents, layout="vertical", **kwargs):
    return {"type": "box", "layout": layout, "contents": contents, **kwargs}


def image(url, **kwargs):
    return {"type": "image", "url": url, "size": "full", "aspectMode": "fit", **kwargs}


def bubble(title, contents, hero=None):
    result = {"type": "bubble", "size": "mega", "styles": {"body": {"backgroundColor": BG},
              "header": {"backgroundColor": BG}}, "header": box([
                  text("VALORANT / PERSONAL ASSISTANT", "xxs", RED, weight="bold"),
                  text(title, "xl", weight="bold", margin="md")]),
              "body": box(contents, spacing="md", paddingAll="20px")}
    if hero:
        result["hero"] = hero
    return result


def notice(title, detail):
    return bubble(title, [text(detail, "sm", MUTED)])


def menu():
    commands = [("商店", "今日造型"), ("夜市", "限定折扣"), ("配件", "每週精選"),
                ("錢包", "VP / RP / KC"), ("戰績", "最近五場"), ("牌位", "段位與 RR"),
                ("好友", "遊戲在線好友"), ("好友提醒", "上線推播開關")]
    rows = []
    for i in range(0, len(commands), 2):
        rows.append(box([box([text(cmd, "lg", weight="bold"), text(label, "xs", MUTED)],
                              flex=1, paddingAll="12px", backgroundColor=PANEL, cornerRadius="12px",
                              action={"type": "message", "label": cmd, "text": cmd})
                         for cmd, label in commands[i:i + 2]], "horizontal", spacing="md"))
    return bubble("特戰英豪 · 指令中心", [text("點選卡片即可查詢", "sm", MUTED), *rows])


def item_card(item: dict, section: str, remaining: int | None = None):
    hero = box([image(item["image"], aspectRatio="16:9")], paddingAll="16px", backgroundColor=PANEL) \
        if item.get("image") else box([text("預覽尚未收錄", "md", MUTED, align="center")],
                                      height="170px", justifyContent="center", backgroundColor=PANEL)
    contents = [text(item["name"], "lg", weight="bold")]
    if item.get("discount"):
        contents.append(box([text(f"−{item['discount']}%", "sm", GREEN, weight="bold"),
                             text(f"原價 {item['original']:,} {item['currency']}" if item.get("original") is not None
                                  else "原價未提供", "xs", MUTED)], "horizontal", spacing="md"))
    amount = item.get("price")
    contents.append(text(f"{amount:,} {item.get('currency', 'VP')}" if amount is not None else "價格未提供",
                         "xxl", RED, weight="bold"))
    if remaining is not None:
        contents.append(text(f"更新倒數 {max(0, remaining) // 3600} 小時 {(max(0, remaining) % 3600) // 60} 分",
                             "xs", MUTED))
    return bubble(section, contents, hero)


def carousel(cards: list[dict]):
    if not cards:
        return notice("暫無資料", "目前沒有可顯示的項目。")
    return {"type": "carousel", "contents": cards[:12]}


def messages(cards: list[dict], alt="Valorant 助手") -> list[dict]:
    output = []
    for content in cards:
        if content["type"] == "carousel":
            chunks = [content["contents"][i:i + 12] for i in range(0, len(content["contents"]), 12)]
            output.extend({"type": "flex", "altText": alt, "contents": {"type": "carousel", "contents": chunk}}
                          for chunk in chunks)
        else:
            output.append({"type": "flex", "altText": alt, "contents": content})
    # Each request has at most 5 messages; callers batch pushes when needed.
    for message in output:
        if len(json.dumps(message["contents"], ensure_ascii=False).encode()) > 50000:
            raise ValueError("Flex payload 超過大小限制。")
    return output


def progress(label, current, target=None, subtitle=None):
    contents = [text(label, "md", weight="bold"),
                text(f"{current:,} / {target:,}" if target else f"{current:,} · 目標尚未提供", "sm", MUTED)]
    if target and target > 0:
        percent = min(100, max(0, round(current / target * 100)))
        contents.append(box([box([], backgroundColor=GREEN, width=f"{max(1, percent)}%", height="6px")],
                            backgroundColor=PANEL, height="6px", cornerRadius="3px"))
    if subtitle:
        contents.append(text(subtitle, "xs", MUTED))
    return box(contents, spacing="sm", paddingAll="12px", backgroundColor=PANEL, cornerRadius="10px")


def match_card(match: dict, puuid: str, assets, title="對戰結算", rr_update=None):
    player = next((x for x in match.get("players", []) if x["subject"] == puuid), None)
    if not player:
        return notice("戰績", "這場對戰沒有此帳號的玩家資料。")
    info = match.get("matchInfo", {})
    map_info = assets.map(info.get("mapId", ""))
    agent = assets.lookup("agents", player.get("characterId", ""))
    stats = player.get("stats") or {}
    analysis = match_stats(match, puuid)
    teams = match.get("teams") or []
    own = next((x for x in teams if x["teamId"] == player.get("teamId")), {})
    enemy = next((x for x in teams if x["teamId"] != player.get("teamId")), {})
    if own and enemy:
        result = analysis["result"] or "勝負未提供"
        score = f"{own.get('roundsWon', '—')} : {enemy.get('roundsWon', '—')}"
    else:
        result, score = "對戰結束", "個人賽"
    color = GREEN if result == "勝利" else RED if result == "敗北" else MUTED
    overlay = [text(result, "xl", color, weight="bold"), text(score, "xxl", weight="bold"),
               text(map_info.get("displayName", "未知地圖"), "sm")]
    layer = box(overlay, position="absolute", offsetStart="18px", offsetTop="18px",
                paddingAll="12px", backgroundColor="#101923DD", cornerRadius="12px", width="180px")
    hero_contents = []
    if map_info.get("splash"):
        hero_contents.append(image(map_info["splash"], aspectMode="cover", aspectRatio="16:9"))
    hero_contents.append(layer)
    if agent.get("displayIcon"):
        hero_contents.append(box([image(agent["displayIcon"], aspectRatio="1:1", aspectMode="cover")],
                                 position="absolute", offsetEnd="18px", offsetBottom="16px", width="72px",
                                 height="72px", cornerRadius="36px", backgroundColor=PANEL))
    hero = box(hero_contents, height="200px", backgroundColor=PANEL, paddingAll="0px")
    acs = analysis["acs"]
    kda = " / ".join(str(stats.get(k, "—")) for k in ("kills", "deaths", "assists"))
    contents = [
        text(agent.get("displayName", "特務"), "lg", weight="bold"),
        box([box([text("K / D / A", "xs", MUTED), text(kda, "xl", weight="bold")], flex=2),
             box([text("ACS", "xs", MUTED), text(round(acs) if acs is not None else "—", "xl", RED,
                                                    weight="bold")], flex=1)], "horizontal")]
    duration = info.get("gameLengthMillis")
    contents.append(text(match_time(info) + (f" · {duration // 60000} 分 {duration // 1000 % 60} 秒" if duration else ""), "xs", MUTED))
    kd = "無死亡" if stats.get("deaths") == 0 and "kills" in stats else display(analysis["kd"])
    contents.extend([metrics([("ADR", analysis["adr"]), ("爆頭命中比例", display(analysis["hs"], "%")), ("K/D", kd)]),
                     metrics([("首殺 / 首死", pair(analysis["first_kills"], analysis["first_deaths"])),
                              ("安裝 / 拆除", pair(analysis["plants"], analysis["defuses"]))])])
    if analysis.get("position"):
        contents.append(text(f"ACS 排名 {analysis['position']} / {analysis['player_count']} · {stats.get('roundsPlayed', '—')} 回合", "sm", GREEN))
    if analysis["multikills"] is not None:
        contents.append(metrics([(f"{i} 殺回合", n) for i, n in analysis["multikills"].items()]))
    if analysis["spent"] is not None:
        contents.append(text(f"平均每回合花費 {analysis['spent']:,.0f} 信用點", "xs", MUTED))
    casts = stats.get("abilityCasts") or {}
    if casts:
        contents.append(metrics([(label, casts.get(key)) for label, key in
                                 (("技能 C", "grenadeCasts"), ("技能 Q", "ability1Casts"),
                                  ("技能 E", "ability2Casts"), ("終極技能", "ultimateCasts"))]))
    if info.get("completionState") == "Surrendered":
        contents.append(text("本場以投降結束", "xs", MUTED))
    if rr_update:
        delta = rr_update.get("RankedRatingEarned")
        label = f"{delta:+} RR" if isinstance(delta, (int, float)) else "RR 未提供"
        contents.append(text("本場競技積分 " + label, "lg", GREEN if delta is not None and delta >= 0 else RED))
        contents.append(metrics([("RR 前 → 後", f"{display(rr_update.get('RankedRatingBeforeUpdate'))} → {display(rr_update.get('RankedRatingAfterUpdate'))}"),
                                 ("表現加成", rr_update.get("RankedRatingPerformanceBonus")),
                                 ("AFK 懲罰", rr_update.get("AFKPenalty"))]))
    contents.append(text("爆頭比例＝頭部命中 / 全部部位命中；— 表示資料未提供。", "xxs", MUTED))
    return bubble(title + " · " + (info.get("queueID") or "模式未提供"), contents, hero)


def display(value, suffix=""):
    return "—" if value is None else f"{value}{suffix}"


def pair(a, b):
    return f"{display(a)} / {display(b)}"


def metrics(values):
    return box([box([text(label, "xxs", MUTED), text(display(value), "md", weight="bold")], flex=1)
                for label, value in values], "horizontal", spacing="sm", paddingAll="10px",
               backgroundColor=PANEL, cornerRadius="8px")


def summary_card(matches, puuid):
    stats = recent_summary(matches, puuid)
    known = stats["wins"] + stats["losses"] + stats["draws"]
    rate = round(stats["wins"] / known * 100, 1) if known else None
    kda = " / ".join(display(stats[k]) for k in ("kills", "deaths", "assists"))
    return bubble(f"近 {stats['count']} 場 · 表現總覽", [
        metrics([("勝 / 敗 / 和", f"{stats['wins']} / {stats['losses']} / {stats['draws']}"),
                 ("勝率", display(rate, "%"))]), text("累計 K / D / A", "xs", MUTED), text(kda, "xl", weight="bold"),
        metrics([("加權 ACS", stats["acs"]), ("加權 ADR", stats["adr"]), ("爆頭比例", display(stats["hs"], "%"))]),
        text("ACS、ADR 以回合數加權；爆頭比例以命中數加權。不同模式混合時僅供觀察。", "xs", MUTED),
        text(f"勝負未提供 {stats['unknown']} 場；— 表示資料不足。", "xxs", MUTED)])
