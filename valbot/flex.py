from __future__ import annotations

import json

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
                ("任務", "本期目標"), ("通行證", "等級與獎勵")]
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


def match_card(match: dict, puuid: str, assets, title="對戰結算"):
    player = next((x for x in match.get("players", []) if x["subject"] == puuid), None)
    if not player:
        return notice("戰績", "這場對戰沒有此帳號的玩家資料。")
    info = match.get("matchInfo", {})
    map_info = assets.map(info.get("mapId", ""))
    agent = assets.lookup("agents", player.get("characterId", ""))
    stats = player.get("stats") or {}
    teams = match.get("teams") or []
    own = next((x for x in teams if x["teamId"] == player.get("teamId")), {})
    enemy = next((x for x in teams if x["teamId"] != player.get("teamId")), {})
    if own and enemy:
        result = "勝利" if own.get("won") else ("平手" if own.get("roundsWon") == enemy.get("roundsWon") else "敗北")
        score = f"{own.get('roundsWon', 0)} : {enemy.get('roundsWon', 0)}"
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
    rounds = stats.get("roundsPlayed", 0)
    acs = round(stats.get("score", 0) / rounds) if rounds else None
    kda = f"{stats.get('kills', 0)} / {stats.get('deaths', 0)} / {stats.get('assists', 0)}"
    return bubble(title + " · " + (info.get("queueID") or "custom"), [
        text(agent.get("displayName", "特務"), "lg", weight="bold"),
        box([box([text("K / D / A", "xs", MUTED), text(kda, "xl", weight="bold")], flex=2),
             box([text("ACS", "xs", MUTED), text(acs if acs is not None else "—", "xl", RED,
                                                    weight="bold")], flex=1)], "horizontal")], hero)
