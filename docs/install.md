# 安裝與維護：Ubuntu／Windows

第一次安裝只需要三件事：取得 LINE 三項資料、完成 Riot 登入、執行安裝器。Ubuntu 安裝器會處理 Python 3.12、cloudflared、每日排程、systemd 服務及 LINE Webhook 網址，不需要購買網域或手動開兩個終端機。

已在 Ubuntu 安裝成功的人只需更新，不需要重填設定：

```bash
cd "$HOME/valbot"
bash update-linux.sh
```

## 1. 先準備 LINE 的三項資料

1. 到 [LINE Official Account Manager](https://manager.line.biz/) 建立官方帳號，設定 → Messaging API → 啟用，選擇 Provider。
2. 開啟 [LINE Developers Console](https://developers.line.biz/console/)，登入同一個管理帳號 → Provider → 自己的 **Messaging API Channel**。
3. 在 **Messaging API** 分頁往下捲，找到 **Channel access token (long-lived)** → 按 **Issue**。複製整段 Token。
4. 在 **Basic settings** 分頁找到 **Channel secret**，複製它。
5. 同一個 Basic settings 分頁最下方找到 **Your user ID**，應為 `U` 開頭共 33 個字元。不是自己的 LINE ID、暱稱、Channel ID 或官方帳號 ID。
6. 用自己的手機將這個 Bot 加為好友。

| 精靈要求 | 要貼哪個欄位 | 用途 |
| --- | --- | --- |
| Channel Access Token | Developers Console → Messaging API → Channel access token | Bot 回覆及推播 |
| Channel Secret | Developers Console → Basic settings → Channel secret | 驗證 Webhook 簽章 |
| LINE User ID | Developers Console → Basic settings → Your user ID | 只授權你查詢、收推播 |

如果畫面只有「Channel ID、Channel secret、Webhook URL」，通常還在 Official Account Manager；按 Developers Console 連結進入開發者後台。Your user ID 看不到時，要先把管理用 Business ID 連結到自己的 LINE 帳號；不必猜一個 ID。

資料只貼到本機設定精靈。Access Token 與 Secret 的輸入是隱藏的，貼上後看不到字元屬正常。

依據：[建立 Messaging API Channel](https://developers.line.biz/en/docs/messaging-api/getting-started/)、[取得自己的 User ID](https://developers.line.biz/en/docs/messaging-api/getting-user-ids/)。

## 2. Ubuntu 筆電：建議的長期運作主機

### 新安裝

開啟 Ubuntu 的終端機（Ctrl+Alt+T），以平常的使用者登入，貼上：

```bash
sudo apt-get update && sudo apt-get install -y curl && curl -fsSL https://raw.githubusercontent.com/PearcePin/valbot/main/install.sh | bash
```

不要在最前面加 `sudo bash`。只有系統套件及服務設定會要求 sudo；輸入 Ubuntu 登入密碼時畫面不顯示字元。

安裝器依序執行：

1. 安裝缺少的 Git、curl、cron；下載專案至 `~/valbot`。
2. 自動用 uv 建立 Python **3.12** 虛擬環境並安裝套件。系統的 Python 3.14 留在原處，不用降版，也不用手動輸入 `python3 -m venv`。
3. 開啟設定精靈，完成 Riot 與 LINE 驗證，建立每日 08:05 排程。
4. 依 x86_64／ARM64 自動下載 Linux 版 cloudflared。
5. 驗證 systemd 設定，再註冊並啟動 `valbot.service`，設定開機啟動。背景服務同時管理 Bot 與 Tunnel，Tunnel 可連線並通過 LINE 驗證後自動更新 Webhook。

若專案目錄已存在，直接下載模式會嘗試安全的 `git pull --ff-only`，保留 `data/`；原始碼有修改時會停止，避免覆蓋。若已有相容的虛擬環境會沿用；不相容或從 Windows 搬來的 `.venv` 會改名為 `.venv.backup-日期-編號`，再建立 Linux 環境，不會刪掉原有登入設定。

### 已經 clone 過，尚未完成安裝

不必刪掉整個資料夾，執行：

```bash
cd "$HOME/valbot"
git pull --ff-only
bash install.sh --local
```

發現已保存設定時，安裝器會問是否保留。按 Enter 就沿用；輸入 `n` 才重新設定登入。若先前自己手動開過 Bot／Tunnel，先在那兩個終端機按 Ctrl+C，避免佔用 8000 埠，再執行安裝器。

### 瀏覽器登入：選 ssid，不要先選帳密

Ubuntu 安裝器直接使用瀏覽器方式，步驟如下：

1. 區域：台灣帳號按 Enter 使用 **AP**。
2. 選 **1 ssid**，在瀏覽器完成 Riot 登入及 2FA。
3. 回到終端機按 Enter，精靈開啟 `https://auth.riotgames.com/`。這頁顯示 **404 沒關係**。
4. 在這個分頁按 F12／Ctrl+Shift+I → **Application**。若沒有此分頁，按上方 **»**。
5. 左側 **Storage → Cookies → https://auth.riotgames.com**。
6. 找 **Name 是 `ssid`** 的那列，雙擊 **Value**，複製完整值。不要複製整列；不是 Wi-Fi SSID。
7. 回精靈貼上 ssid，按 Enter。輸入隱藏，畫面沒有字元是正常的。
8. 登入驗證成功後，依序貼 LINE Token、Secret、User ID。手機收到指令中心表示推播測試成功。

若 ssid 被拒絕，精靈可原地重試或選 **3 完整 Cookie**。F12 → **Network → Preserve log／Keep log**，再走一次 Riot 登入，找到 `auth.riotgames.com` 的請求 → **Headers → Request Headers → Cookie**，複製整個值，應包含 `ssid=...`。不是 Response Headers 的 Set-Cookie，也不是 Application 表格中的整列。

選 **2 網址** 只適合暫時測試：要貼登入跳轉後包含 `access_token` 的完整網址。404 不影響 token 驗證；原本的 authorize 連結、帳號管理頁及一般首頁都不算。只有網址 token 且沒有成功驗證的 Cookie 時，通常約一小時後需重登，不能當成永久登入。

完整登入排錯見 [登入說明](login.md)。Riot 要求互動驗證時只能重新登入，安裝器無法保證 Cookie 永久有效。

### 最後一次 LINE 設定

在 Developers Console → Messaging API：

1. 將 **Use webhook** 打開。
2. 停用官方帳號內建的自動回覆，避免它回覆「本帳號無法個別回覆」或與 Bot 重複回覆。
3. 查看服務啟動狀態：

```bash
sudo journalctl -u valbot.service -n 50 -f
```

看到 **Webhook verified and updated** 與 **Bot service is ready.** 表示 Tunnel 及 Webhook 驗證完成。若提示 `Enable Use webhook`，回 LINE 開啟該開關。

**Ctrl+C 只會離開日誌，不會停止背景服務**。之後可關閉終端機，Bot 繼續運作。用 LINE 按「商店」測試互動；安裝時收到推播不代表 Webhook 已啟用，這兩個測試都要成功。

Quick Tunnel 不需要自有網域，網址可能因重啟改變，服務會重新驗證後更新。Cloudflare 對 Quick Tunnel 不提供 uptime 保證。[Quick Tunnel 說明](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)

### 電源、時間與日常維護

- Ubuntu 設定 → 電源 → 關閉自動休眠；確認闔蓋後不會休眠。終端機可關，筆電需開機且連網。
- 每日 08:05 使用主機時區。台灣可先執行 `sudo timedatectl set-timezone Asia/Taipei`，再用 `.venv/bin/python setup.py --schedule-only` 重新註冊排程。
- 看服務：`systemctl status valbot.service --no-pager`。
- 看最近日誌：`sudo journalctl -u valbot.service -n 50 --no-pager`。
- 重啟：`sudo systemctl restart valbot.service`。
- 暫停：`sudo systemctl stop valbot.service`。
- 停止及取消開機啟動：`sudo systemctl disable --now valbot.service`。每日商店的 cron 是另一個排程，需要另行移除。
- 更新：`cd "$HOME/valbot"`，再 `bash update-linux.sh`。它會安裝相依套件及重啟服務，不需要重跑精靈，也不用一直開 journalctl。

Cookie 失效時，重新登入後重啟：

```bash
cd "$HOME/valbot"
.venv/bin/python setup.py --login-method browser
sudo systemctl restart valbot.service
```

## 3. Windows 10／11：本機測試

在一般 PowerShell 貼上：

```powershell
& ([scriptblock]::Create((Invoke-WebRequest -UseBasicParsing 'https://raw.githubusercontent.com/PearcePin/valbot/main/install.ps1').Content))
```

安裝器會在缺少 Git 時使用 winget 安裝（若沒有 winget，依提示安裝 [Git for Windows](https://git-scm.com/download/win) 並重開 PowerShell）。自動用 uv 準備 Python 3.12，不會把 `py -3` 指向的 Python 3.14 拿來建立不相容環境。

預設路徑是 `C:\Users\你的名字\valbot`。完成設定後，下載 Windows 版 cloudflared。先開 Riot Client 登入並進 VALORANT 主選單，精靈預設選 **3 本機 Riot Client**，不用找 ssid；之後 Client 需要保持登入、開啟。

只要一個終端機啟動 Bot＋Tunnel，並自動驗證及更新 Webhook：

```powershell
cd "$env:USERPROFILE\valbot"
.\.venv\Scripts\python.exe -m valbot.daemon
```

看到 `Bot service is ready.` 後測試 LINE。**Windows 這個終端機要保持開啟**，Ctrl+C 會停止 Bot 和 Tunnel；鎖定螢幕可繼續，關機／休眠不行。每日工作排程器任務使用 pythonw 隱藏執行，與 Webhook 常駐程序是兩件事。想關掉終端機又長期運作，使用上述 Ubuntu 服務部署。

已 clone 的 Windows 專案：

```powershell
cd "$env:USERPROFILE\valbot"
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -Local
```

只更新程式時，先 Ctrl+C 停掉 launcher，再 `git pull --ff-only`、`.\.venv\Scripts\python.exe -m pip install -r requirements.txt`，最後重跑 `.\.venv\Scripts\python.exe -m valbot.daemon`。

同一個 LINE Channel 同時只開一台主機，否則兩台會搶著更新 Webhook，造成「在 Windows 清掉測試後 Ubuntu 也不能用」這類問題。Ubuntu 接手前先停止 Windows 測試程序；不需要刪除 GitHub 專案或重新發行 Token。

## 4. 你可能遇到的錯誤

| 畫面／症狀 | 原因與做法 |
| --- | --- |
| `pythn3 not found` | 指令拼字是 `python3`；新版安裝器不需手動打這個指令。 |
| Python 3.14、pydantic.v1 不相容 | 使用新版安裝器，它建立 3.12 並備份不相容 .venv，不必移除系統 Python。 |
| 目的資料夾已存在 | 用 `bash install.sh --local` 或 `install.ps1 -Local`，不要先清掉 `data/`。 |
| 帳密正確仍登入失敗 | 改用瀏覽器完成 CAPTCHA／2FA；Windows 可用本機 Riot Client。 |
| 登入後網頁 404 | 不代表 token／Cookie 無效；依精靈 ssid 流程，或貼含 `access_token` 的網址。 |
| Cookie 未含 ssid | 完整 Cookie 模式需 `ssid=值; 其他cookie=值`；單一 ssid 模式只貼 Value。不要混用格式。 |
| `工作階段失效`／HTTP 406 | 先更新；重新完成瀏覽器登入，試完整 Cookie。仍被拒絕時只提供錯誤文字，不分享憑證。 |
| 找不到 Token | 到 Developers Console，不是 Official Account Manager，Messaging API 分頁最下方 Issue。 |
| 找不到 User ID | Basic settings 最下方 Your user ID，必要時連結 Business ID 與 LINE。 |
| Bot 回「無法個別回覆」 | LINE 的預設自動回覆尚未關掉，或 Use webhook 未開啟。 |
| `WorkingDirectory path is not absolute`／bad-setting | 舊腳本把路徑加了引號。更新後跑 `bash deploy-linux.sh`；新版先用 systemd-analyze 驗證。 |
| `unit ... not loaded` | 使用完整名稱 `valbot.service`，先跑 deploy-linux.sh；不要先對不存在的服務 reset-failed。 |
| 8000 埠被佔用 | 停掉舊手動 Bot 程序，再啟動 systemd；不要同時開兩份。 |
| 手動 cloudflared 關終端就不能用 | 手動程序跟著退出；Ubuntu 改用 systemd。Quick Tunnel 的條款提示與缺 config.yml 訊息不一定代表失敗。 |
| Tunnel 網址不同了 | 等待服務重新驗證並更新，檢查 Use webhook 和日誌；不用自己買網域。 |
| 更新後不能回覆 | 看 `systemctl status valbot.service` 和最近 50 行日誌，確認新 Tunnel 驗證成功；更新腳本本身已重啟服務。 |
| LINE HTTP 401／403／404 | 檢查 Token、User ID、是否加好友及正確 Channel；不要把 Channel ID 當 User ID。 |
| 私人 repo 的 raw URL 顯示 404 | 使用已登入 Git 的 clone，再執行本機安裝器，不要將 GitHub Token 貼在公開指令中。 |

## 5. 進階選項與資料

- Linux `install.sh --no-deploy` 只設定及下載，稍後再 `bash deploy-linux.sh`；適用沒有 systemd 的環境，自行管理 Webhook 程序。
- Linux `--no-setup --no-deploy`／Windows `-NoSetup` 適合事先準備環境，不會完成帳號設定；一般安裝不要加這些選項。
- Linux `VALBOT_INSTALL_DIR` 或 Windows `-Destination` 可指定目錄；`--local`／`-Local` 使用當前 checkout。
- 想自選已安裝的相容 Python，可設定 `VALBOT_PYTHON`（Linux）；預設自動 Python 3.12 最簡單。
- `data/` 保存加密設定、登入、訊息和金鑰。Git 更新不包含它；不要只複製 token 檔卻漏掉 vault.key。
- 換電腦請重新跑安裝器；Windows 虛擬環境不能直接在 Linux 使用。Windows 的本機 Riot Client 工作階段也不能搬到 Ubuntu。
- 每日推播：Linux `crontab -l`；Windows 工作排程器中 `ValorantLineBot-*`。重新設定只替換此專案的排程。

Python 自動安裝依據：[uv 安裝](https://docs.astral.sh/uv/getting-started/installation/)、[指定 Python 版本](https://docs.astral.sh/uv/guides/install-python/)。此專案使用非官方 Riot 遊戲／聊天介面，登入與聊天接收仍需在實際主機驗證。
