# Valorant LINE Bot

特戰英豪個人 LINE 助手，支援 **Ubuntu 與 Windows 10／11**。使用 FastAPI、LINE 官方 SDK v3、httpx，以 Flex Message 呈現商店、戰績、牌位與 Riot 好友資訊。安裝器自動準備 **Python 3.12**，不需要移除系統 Python 3.14。

**第一次安裝請看：[詳細安裝與排錯](docs/install.md)。** 包含 Token、User ID、ssid 的確切位置、404／HTTP 406、Cloudflare、背景服務、更新及換電腦步驟。[Riot 登入說明](docs/login.md)

## 功能

| 指令 | 內容 |
| --- | --- |
| 商店 | 今日四把造型、稀有度色背景、圖片、VP 價格與更新倒數 |
| 夜市 | 六把折扣造型、稀有度色背景、原價及折後價，未開放時提示 |
| 配件 | 本週卡面、吊飾、噴漆及 KC 價格 |
| 錢包 | VP／RP／KC 餘額 |
| 戰績 | 每頁 10 場，可持續翻頁；勝率、K/D/A、ACS／ADR、爆頭比例、首殺／首死、多殺、安裝／拆除、排名、經濟、技能及競技 RR |
| 牌位 | 本季徽章、RR、勝率、定級進度、排行榜、近期 RR 變動與賽季紀錄 |
| 好友 | 手動查看全部 Riot 好友及在線狀態，在同一張卡上選人私訊 |
| 好友訊息 | 手動短暫連線查看收到的私訊、本機訊息列表、翻頁、選擇回覆 |

每日 **08:05（主機本地時區）**推送商店、配件、精選組合包；夜市開放時一併加入。查詢回覆先顯示 **指令中心 → 查詢結果**。僅設定的 LINE User ID 可查詢，群組不處理。任務、通行證、自動戰報與自動好友上線提醒已移除。

戰績按上一頁／下一頁，或輸入 **戰績 2** 查看第 11–20 場。總歷史不設 100 場上限，實際範圍以 Riot 可提供的紀錄為準；統計只涵蓋本頁，明細缺少時顯示未提供。ACS／ADR 依回合數加權；爆頭比例是頭部命中／全部部位命中，不是射擊命中率。

好友私訊：**好友 → 選收件人 → 輸入最多 500 字 → 預覽 → 確認送出**。草稿 10 分鐘內有效，輸入「取消私訊」可取消。送出時再次檢查帳號與好友關係，不會自動重送狀態不明的訊息；「已提交」不代表對方已收到或已讀。

**好友訊息完全手動，不保持聊天連線、不主動推播。** 按下才短暫收信 5 秒，或保存其他手動聊天操作期間收到的私訊。只接受互為好友的私人文字，本機加密保留最近 200 則、每則最多 2000 字；可按「回覆這位好友」建立草稿。「標為已看」只改本機紀錄，不送 Riot 已讀回條。沒收取到訊息不代表朋友從未傳訊息：Riot 不保證回傳離線或已送往其他 Client 的聊天，不能當成完整聊天歷史。實際收發仍需部署後驗證。

## 一行指令安裝

Ubuntu（一般使用者終端機，不要 `sudo bash`）：

```bash
sudo apt-get update && sudo apt-get install -y curl && curl -fsSL https://raw.githubusercontent.com/PearcePin/valbot/main/install.sh | bash
```

自動處理 Git／cron、Python 3.12、套件、Riot／LINE 設定、cloudflared 及開機自啟的 systemd 服務。設定成功後，服務驗證並更新 LINE Webhook；你仍需在 Developers Console 開啟 **Use webhook**、關閉內建自動回覆。看到 **Bot service is ready.** 後可以關終端機；筆電要保持開機、連網且不休眠。

Windows PowerShell：

```powershell
& ([scriptblock]::Create((Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/PearcePin/valbot/main/install.ps1').Content))
```

缺少 Git 時使用 winget 安裝，再自動準備 Python 3.12、套件、設定及 cloudflared。完成後用一個終端機啟動 Bot＋Tunnel：

```powershell
cd "$env:USERPROFILE\valbot"
.\.venv\Scripts\python.exe -m valbot.daemon
```

Windows 此終端機需保持開啟，Ctrl+C 會停止；長期背景運作推薦 Ubuntu。Windows 設定精靈預設讀取已登入的 Riot Client，Client 需保持登入、開啟。Ubuntu 預設瀏覽器 Cookie，登入完成的 404 頁面不代表登入失敗。

預設專案為家目錄 `valbot`。已 clone 者更新後執行 **`bash install.sh --local`**／**`powershell -ExecutionPolicy Bypass -File .\install.ps1 -Local`**，不必刪掉舊專案。相容環境與設定會保留，不相容的 .venv 會先改名備份。若 raw URL 無法讀取私人 repo，先透過已登入 Git clone，再執行本機安裝器。

## LINE 憑證從哪裡拿

1. 在 [Official Account Manager](https://manager.line.biz/) 建立官方帳號並啟用 Messaging API。
2. 到 [Developers Console](https://developers.line.biz/console/) → Provider → **Messaging API Channel**。
3. **Messaging API** 分頁最下方 → **Channel access token (long-lived) → Issue**。
4. **Basic settings** → **Channel secret**；同頁最下方 **Your user ID**（U 開頭共 33 字）。
5. 手機將 Bot 加為好友，將三項資料貼入本機精靈。它會測試登入、商店、LINE 憑證及推播；成功才保存設定。

找不到 Token 時通常是停在官方帳號管理後台；必須進 Developers Console。完整欄位對照及登入步驟見 [安裝說明](docs/install.md)。不要分享 Token、Cookie、登入網址或 data/。

## 更新與維護

Ubuntu 已安裝者只需：

```bash
cd "$HOME/valbot"
bash update-linux.sh
```

自動拉取版本、安裝套件及重啟服務，保留 `data/` 和排程，不需重新登入。原始碼有未保存變更時會停止，更新失敗沒有自動 rollback；依錯誤修復後再啟動。cloudflared 不會每次更新都重下載。

```bash
systemctl status valbot.service --no-pager
sudo journalctl -u valbot.service -n 50 --no-pager
sudo systemctl restart valbot.service
```

日誌加 `-f` 可即時追蹤；Ctrl+C 只離開日誌，不會關服務。Quick Tunnel 不需購買網域，網址更換後服務會更新 Webhook；[Cloudflare 不保證 Quick Tunnel uptime](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)。同一個 LINE Channel 不要同時啟動 Windows／Ubuntu 兩份，避免搶著更新 Webhook。

Riot Cookie 失效需重新執行 `.venv/bin/python setup.py --login-method browser`，再重啟服務。台灣每日 08:05 需設定主機 Asia/Taipei 時區，詳見安裝說明。原生 cron／Windows 工作排程器的每日推播與常駐 Webhook 是兩件事，停掉服務不會自動取消每日排程。

## 資料與開發

Riot 遊戲／聊天使用非官方介面，可能變更或要求 CAPTCHA／2FA；程式不繞過驗證，不保證永久登入。圖片與 UUID 來自 [Valorant-API](https://valorant-api.com/)，未知欄位不編造。Python 支援 3.11–3.13，安裝器預設 3.12。

密碼不落地；LINE 憑證、Riot session、訊息、草稿及推播 checkpoint 使用 Fernet 加密。`data/` 和 vault.key 需一起保護，加密無法防止同一 OS 帳號讀取。Linux 目錄 700；Windows 建立時移除繼承 ACL。Git 排除 data/、虛擬環境及其備份；可用 `VALBOT_DATA_DIR` 自訂資料位置，但需自行配合 Tunnel 路徑與部署。移機請重新安裝／設定，不要直接搬 Windows .venv 到 Linux。

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest -q
```

測試以模擬 Riot／LINE／安裝器驗證，不會使用真實帳密或改系統服務；GitHub Actions 執行 Ubuntu／Windows、Python 3.11／3.12。`examples/flex-messages.json` 使用公開圖片與示範數據，可放入 [LINE Flex Simulator](https://developers.line.biz/flex-simulator/) 檢視；`python -m tools.export_flex_samples` 重建。

[功能候選清單](docs/feature-catalog.md) · [詳細安裝](docs/install.md) · [登入排錯](docs/login.md) · [Riot 端點研究](https://valapidocs.techchrism.me/) · [VALORANT XMPP](https://github.com/techchrism/valorant-xmpp-playground)
