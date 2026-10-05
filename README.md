# Valorant LINE Bot

特戰英豪個人 LINE 助手，支援 Ubuntu Linux 與 Windows 10/11。採用 **FastAPI + LINE 官方 SDK v3 + httpx**，以 Flex Message 顯示遊戲資訊。原生 cron／工作排程器執行每日推播，不必讓 Webhook 常駐才可推播。Python 3.11 以上。

## 功能

| 指令 | Flex 內容 |
| --- | --- |
| 商店 | 每日四把武器造型、圖片、VP 價格與更新倒數 |
| 夜市 | 開放時六把武器、原價、折扣與折後價 |
| 配件 | 本週卡面、吊飾、噴漆與 KC 價格 |
| 錢包 | VP／RP／KC 餘額 |
| 戰績 | 最近一場地圖背景、圓形特務頭像、勝負色、比分、K/D/A、ACS |
| 牌位 | 本期段位徽章、RR 與最近競技對戰 RR 變動 |
| 任務 | 任務目標、進度條、XP 與到期時間 |
| 通行證 | 本期等級、下一階 XP 與獎勵圖片 |

每日 **08:05（執行主機本地時區）**推送每日商店、配件、精選組合包，夜市開放時自動加入。加好友或未知指令會顯示可點選功能選單。僅設定的 LINE User ID 能查看資料，群組事件不處理。

## 一行指令安裝

先安裝 **Git、Python 3.11+**；Ubuntu 另需 `python3-venv`、`cron` 並啟動 cron 服務。以下透過 Git 下載，支援已登入的私人儲存庫；私人 repo 需先完成 GitHub／Git Credential Manager 認證。

Linux：

```bash
git clone https://github.com/PearcePin/valbot.git "$HOME/valbot" && bash "$HOME/valbot/install.sh" --local
```

Windows PowerShell：

```powershell
git clone https://github.com/PearcePin/valbot.git "$env:USERPROFILE\valbot"; if ($LASTEXITCODE -eq 0) { powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\valbot\install.ps1" -Local }
```

預設安裝至使用者家目錄 `valbot`，若目錄已存在，clone 會停止。可修改 clone 的目的目錄及後面的腳本路徑。`--local`／`-Local` 使用已下載專案；腳本可先開啟檢視。

若儲存庫開放公開讀取，也可直接下載安裝器，由它自動 clone：

```bash
curl -fsSL https://raw.githubusercontent.com/PearcePin/valbot/main/install.sh | bash
```

```powershell
& ([scriptblock]::Create((Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/PearcePin/valbot/main/install.ps1').Content))
```

直接下載模式的自訂目錄：Linux 設定 `VALBOT_INSTALL_DIR`；PowerShell 加入 `-Destination 'C:\Tools\valbot'`。未授權的私人 repo raw URL 會回傳 404，請使用上方 Git 安裝指令。

已 clone 者直接執行：

```bash
# Linux
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python setup.py
```

```powershell
# Windows
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe setup.py
```

## 取得 LINE 憑證

1. 建立 [LINE 官方帳號](https://manager.line.biz/)，在設定中啟用 Messaging API。
2. 至 [LINE Developers Console](https://developers.line.biz/console/) 的 Messaging API Channel，發行 **Channel access token（long-lived）**。
3. 在 Basic settings 找到 **Channel secret** 與 **Your user ID**；手機將 Bot 加為好友。
4. 精靈輸入區域後選擇 Riot 登入方式；**Windows 推薦先登入 Riot Client 並進入遊戲，選本機模式，不需輸入密碼、ssid 或網址**。再輸入 Access Token、Channel Secret、User ID。會測試商店、Token、收件人並傳送功能選單，成功才保存 LINE 設定與註冊排程。

Channel Secret 是 Webhook 驗證所必需，與 Access Token 不同。LINE 額度與封鎖好友狀態會影響推播。

## Riot 登入與資料限制

商店、餘額、任務使用遊戲的**非官方私有端點**，並非 Riot 正式開放的商店 API。Riot 可能調整登入、要求 CAPTCHA 或封鎖直接帳密登入；程式不會繞過驗證。帳密模式支援最多三次 2FA，失敗時切換瀏覽器模式。預設使用新版 `riot_identity`／`multifactor.otp` 欄位，舊協定可用 `setup.py --legacy-auth`。

**登入步驟與 ssid 具體位置：[docs/login.md](docs/login.md)。** Windows 可執行 `python setup.py --login-method local` 自動讀取自己的 Riot Client 登入；每日推播時 Client 需保持登入並開啟，token 過期會重新向本機 Client 取得，不需要 Cookie。切換 Riot 帳號時會拒絕沿用別人的工作階段。

瀏覽器模式預設只需 **ssid**，不必貼跳轉網址。完成網頁登入／2FA 後，精靈會引導開啟 `https://auth.riotgames.com/` 分頁（即使 404 仍可檢視 Cookie），按 F12 → Application（應用程式）→ Storage → Cookies → `https://auth.riotgames.com`，複製 Name 為 **ssid** 那列的 **Value**。這不是 Wi-Fi SSID。輸入後立即向 Riot 測試登入；失敗可原地重試。

進階網址模式支援含 `access_token` 的 playvalorant.com 跳轉網址（含 www／語言路徑／結尾斜線），驗證成功才詢問可選的 ssid。沒有 ssid 的網址 token 通常約一小時有效，**不適合每日無人值守排程**。Cookie 也可能失效；重新執行 `setup.py` 登入即可。不要分享跳轉網址、Cookie 或 Token。

圖片與繁體中文 UUID 資料來自 [Valorant-API](https://valorant-api.com/)。公開圖庫可能落後最新版本；未知圖片或價格會明示未提供，不推算虛假資訊。任務可能只回傳週任務，遊戲內每日 checkpoints 不保證有提供。通行證依本期 Season 關聯識別，圖庫落後時顯示尚未提供。

## Webhook 部署

```bash
# Linux
.venv/bin/python -m uvicorn valbot.app:app --host 127.0.0.1 --port 8000
```

```powershell
# Windows
.\.venv\Scripts\python.exe -m uvicorn valbot.app:app --host 127.0.0.1 --port 8000
```

使用 HTTPS 反向代理或 tunnel 將外部網址轉至本機 8000；在 LINE Console 設定 `https://你的網域/webhook`，按 Verify 並啟用 Use webhook，停用內建自動回覆以免重複。`GET /health` 用於健康檢查。請以**單一 Uvicorn worker**常駐運作，可透過 systemd 或 Windows 服務管理工具管理；安裝精靈只註冊每日推播，不自動建立公開網域或常駐 Webhook 服務。

Webhook 驗證簽章後先寫入加密 SQLite 佇列並回應 LINE，後台處理查詢；以 event ID 防止重送重複回覆。超過 55 秒的佇列事件不再使用過期 reply token；若上游太慢或服務中斷，重新傳送指令即可。

## 排程與操作

精靈成功後自動建立 cron 或 Windows hidden task，以虛擬環境 Python 的絕對路徑執行。Windows 使用 `pythonw.exe` 隱藏視窗，採目前使用者登入權限，**需保持該使用者登入**（鎖定螢幕可運作）；登出、休眠或關機時不保證準點。Ubuntu 必須保持開機且 cron 啟用。若要台灣時間 08:05，先將主機時區設為 Asia/Taipei／Taipei Standard Time，再註冊排程。

```bash
# 以下使用你的 venv Python 替換 python
python setup.py --no-schedule      # 僅設定與登入測試
python setup.py --schedule-only    # 修復／重新註冊排程
python run_daily.py --dry-run      # 取得真實資料，產生 data/daily-preview.json，不推播
python run_daily.py                # 當日最多成功推播一次
python run_daily.py --force        # 手動重送（會再次消耗 LINE 額度）
```

Linux 用 `crontab -l` 查看排程；移除該 `ValorantLineBot-*` BEGIN/END 區塊即可取消。Windows 在 Task Scheduler 找到 `ValorantLineBot-*` 可檢視／停用／刪除。相同專案重新設定只替換自己的排程，不覆蓋其他 cron 任務。

`data/daily.log` 保存輪替錯誤紀錄；Linux 排程輸出另見 `data/cron.log`。推播使用 LINE retry key 與當日 checkpoint，重試途中不重複送出已接受的批次。依賴失效、LINE 額度不足或上游出錯時非零退出；排程隔天再執行，修復後可手動重跑。

## 本機資料與開發

密碼不落地；LINE 憑證、Riot token／cookie、每日 checkpoint 使用 Fernet 加密。金鑰存在同一個 `data/`，需保護整個目錄；加密不防止可讀取該 OS 帳號檔案的人。Linux 目錄權限 700；Windows 建立時移除繼承 ACL 並只授權目前使用者。`data/` 已從 Git 排除，可用 `VALBOT_DATA_DIR` 指向別處。移機時須重新設定，或安全移轉完整資料與重新註冊排程。

```bash
python -m pip install -r requirements-dev.txt
python -m ruff check .
python -m pytest -q
```

測試使用模擬 Riot／LINE 回應，不需要真實帳密。GitHub Actions 已配置 Ubuntu／Windows、Python 3.11／3.12；真實 Riot 登入、LINE 接收與 OS 排程須在部署主機完成實測。

`examples/flex-messages.json` 是使用真實公開圖庫與**示範數值**的七組卡片，包含武器輪播、夜市、卡面、戰績及牌位。複製其中一則的 `contents` 到 [LINE Flex Message Simulator](https://developers.line.biz/flex-simulator/) 檢視正式排版；用 `python -m tools.export_flex_samples` 可重新生成。此檔不含帳號資料，也不會傳送訊息。

API 參考：[LINE Python SDK](https://github.com/line/line-bot-sdk-python)、[LINE Flex](https://developers.line.biz/en/docs/messaging-api/flex-message-elements/)、[Riot 端點研究](https://valapidocs.techchrism.me/)、[Storefront v3 端點記錄](https://gist.github.com/Kavan72/b6e0bfdf21d610148f64df878b8a2cc5)。非 Riot／LINE 官方產品。
