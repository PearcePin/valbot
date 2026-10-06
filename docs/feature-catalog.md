# 可擴充功能候選清單

這是依目前已記錄的私有端點整理的實用候選，不是 Riot 保證完整或永久可用的 API 清單。token 可讀資料受帳號、區域、參與對戰、社交可見範圍限制；欄位缺漏時應顯示未提供。下表尚未加入程式的項目是候選功能。

已實作近五場戰績總覽、ACS／ADR／爆頭比例、首殺／首死、多殺、安裝／拆除、經濟與技能次數、本季牌位詳細資訊、近期 RR 趨勢及賽季紀錄。任務、通行證與自動戰報已按需求移除；以下相關列僅保留作為未來候選。

## 商店／收藏

| 候選功能 | 可用資料／做法 |
|---|---|
| 願望清單上架提醒 | 每日商店 UUID 對照自訂清單；上架才推播 |
| 指定價格／夜市折扣提醒 | 依原價、折後價及折扣篩選 |
| 商店／夜市關閉倒數 | 回傳的剩餘時間，設定到期前通知 |
| 精選組合包明細 | 包內武器、配件、單品折扣與總價 |
| VP／RP／KC 不足提示 | 商店價格對照目前餘額 |
| 造型收藏櫃 | 本人擁有的武器造型及變體 |
| 卡面／吊飾／噴漆／稱號收藏 | 本人擁有物品，UUID 轉圖片 |
| 已解鎖特務 | 本人特務 entitlement |
| 造型升級進度 | 可用的 item upgrade levels，結合公開圖庫 |
| 裝備展示 | 當前武器造型、吊飾、卡面、噴漆與稱號 |
| 收藏／餘額變動通知 | 定期快照差異；無法僅靠餘額判定購買原因 |

依據：[Storefront](https://valapidocs.techchrism.me/endpoint/storefront)、[Owned Items](https://valapidocs.techchrism.me/endpoint/owned-items)、[Item Upgrades](https://valapidocs.techchrism.me/endpoint/item-upgrades)、[Player Loadout](https://valapidocs.techchrism.me/endpoint/player-loadout)。

## 戰績／牌位分析

| 候選功能 | 可用資料／做法 |
|---|---|
| 最近 10／20 場摘要 | match history 分頁；摘要可分批避免 Flex 上限 |
| 勝率、連勝／連敗 | 可取得的最近對戰統計，註明場次 |
| 平均 K/D/A、ACS、傷害 | match details 計算 |
| 爆頭命中比例 | 回合 damage 的 head/body/leg 命中數；需註明統計口徑 |
| 特務／地圖／模式表現 | 依 characterId／mapId／queueID 分組 |
| MVP／排名 | 依對戰分數計算，註明計算方式 |
| 每回合結算 | kills、damage、economy、plant／defuse 欄位 |
| 武器使用統計 | 依回合武器／擊殺欄位計算，不是完整射擊紀錄 |
| 首殺／首死、存活與多殺 | 依擊殺時間及回合事件推導 |
| 同隊對手結算卡 | 本人參與的比賽 player stats；尊重缺漏／匿名資料 |
| RR 趨勢與每場變動 | competitive updates，註明賽季 |
| 賽季牌位歷史 | MMR seasonal info，顯示最高／期末等可推導值 |
| 升段／降段提醒 | 牌位快照或 competitive updates 差異 |
| 對戰結束自動結算 | 輪詢新 match ID，取得完整結算後推播 |
| 每日／每週戰報 | 自建快照彙整，超出 API 保留範圍的歷史需先保存 |
| 排行榜查詢 | 區域排行榜、名次與分數，視該賽季資料 |

依據：[Match Details](https://valapidocs.techchrism.me/endpoint/match-details)、[Match History](https://valapidocs.techchrism.me/endpoint/match-history)、[Competitive Updates](https://valapidocs.techchrism.me/endpoint/competitive-updates)、[Player MMR](https://valapidocs.techchrism.me/endpoint/player-mmr)、[Leaderboard](https://valapidocs.techchrism.me/endpoint/leaderboard)。

## 進度／帳號

| 候選功能 | 可用資料／做法 |
|---|---|
| 帳號等級、XP 與升級進度 | 本人 account XP |
| 首勝獎勵倒數 | account XP 的首勝時間／下次可用時間 |
| 週任務即將到期提醒 | contracts missions expiration |
| 任務／通行證完成通知 | 已完成旗標或進度快照差異 |
| 下一階獎勵預覽 | contracts 定義與圖庫 |
| 通行證達標所需 XP | 剩餘 levels XP；每日目標是計算建議，不是 Riot 預測 |
| 帳號名稱／Tag 展示 | userinfo／name service 可提供的識別資訊 |
| 排隊限制狀態 | penalties 已提供的限制資料；不保證完整封禁原因 |

依據：[Account XP](https://valapidocs.techchrism.me/endpoint/account-xp)、[Contracts](https://valapidocs.techchrism.me/endpoint/contracts)、[Penalties](https://valapidocs.techchrism.me/endpoint/penalties)。

## 好友／即時狀態

| 候選功能 | 可用資料／限制 |
|---|---|
| 指定好友提醒 | XMPP roster 與使用者訂閱清單 |
| 好友選角／進入對戰／回大廳提醒 | presence 的 sessionLoopState 變化 |
| 好友目前地圖／模式／比分 | presence 有公開這些欄位時才顯示 |
| 好友組隊人數／可加入狀態 | presence 公開的 party 欄位；不保證每次有提供 |
| 邀請／好友申請提醒 | XMPP 有發對應事件時可監聽；需進一步測試 |
| 靜音時段／每日通知上限 | Bot 本身的提醒策略，不需要新增 Riot 權限 |

依據：[XMPP 研究](https://github.com/giorgi-o/CrossPlatformPlaying/wiki/Riot-Games)、[XMPP Connection](https://valapidocs.techchrism.me/endpoint/xmpp-connection)。Linux 可以使用 token＋PAS 直接連線，但不能假設能看見隱藏或未公開的好友狀態。

## 本人正在遊戲中才有資料

| 候選功能 | 條件 |
|---|---|
| 排隊／組隊資訊 | 本人存在 party，透過對應遊戲區域 GLZ API 查詢 |
| 選角狀態、地圖與队友特務 | 本人在 pregame；遊戲開著但 Bot 可以在 Linux 查詢 |
| 當前對戰資訊 | 本人正在 current game；不是完整即時戰鬥遙測 |
| 當場造型展示 | 當前比賽 loadouts 可提供的武器造型 |

依據：[Party](https://valapidocs.techchrism.me/endpoint/party)、[Pre-Game Match](https://valapidocs.techchrism.me/endpoint/pre-game-match)、[Current Game Match](https://valapidocs.techchrism.me/endpoint/current-game-match)、[Current Game Loadouts](https://valapidocs.techchrism.me/endpoint/current-game-loadouts)。

## 公開圖庫功能（不需 Riot token）

武器／造型圖鑑、特務技能介紹、地圖圖鑑、牌位徽章、卡面／吊飾預覽、公開版本資料與季節／通行證定義，可用 [Valorant-API](https://valorant-api.com/) 做成 Flex 查詢。價格來源與帳號實際商店仍需區分，缺漏資料不能編造。

## 目前不應保證提供

完整消費流水／付款與退款記錄、好友或陌生人的私人商店與餘額、隱身好友真實狀態、任意玩家全部私人資料、即時敵人位置／血量、完整 replay 影片、永久有效的登入 token。自動改裝備／排隊／鎖角／買物品属于會改變遊戲或帳號狀態的操作，不在本次資料功能中加入。
