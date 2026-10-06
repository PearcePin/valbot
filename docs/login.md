# Riot 登入：Windows 推薦使用 Riot Client

登入被拒絕不代表帳密錯誤。Riot 網頁可能要求 CAPTCHA 或其他互動驗證；直接帳密 API 無法保證可用。精靈預設在 Windows 使用已登入的 Riot Client，在 Ubuntu 使用瀏覽器 Cookie。

## Windows：不需要找 ssid，也不需要貼網址

1. 開啟 **Riot Client**，登入自己的 Riot 帳號並完成 2FA。
2. 啟動 **VALORANT**，進入遊戲主選單。保持 Riot Client 開啟。
3. 在安裝目錄執行：

   ```powershell
   .\.venv\Scripts\python.exe setup.py --login-method local
   ```

4. 輸入區域後，Bot 會讀取本機 Riot Client 提供的登入工作階段，接著要求 LINE 憑證。

不會讀取或保存你的 Riot 密碼。若提示找不到 Client，先確認已登入並進入遊戲，再按 Enter 重試。此模式**每日 08:05 時 Riot Client 也必須保持登入並開啟**，Bot 才能取得更新後的 token；不能將這種工作階段搬到 Ubuntu 使用。若 Client 切換帳號，Bot 會拒絕沿用另一個帳號的資料。

## Chrome／Edge：ssid 的具體位置

ssid 是 Riot 網站保存的登入 Cookie，**不是 Wi-Fi 的網路名稱**。

1. 精靈選 **2 瀏覽器 → 1 ssid 登入**。
2. 在自動開啟的 Riot 網頁完成登入及 2FA。若要求記住登入，選擇記住。
3. 回到終端機按 Enter。精靈會在同一個預設瀏覽器開啟 `https://auth.riotgames.com/`。
4. 這個頁面可能顯示 404／空白；正常，目的是查看這個網域的 Cookie。
5. 在該分頁按 **F12** 或 **Ctrl+Shift+I** 開啟開發者工具。
6. 選上方 **Application（應用程式）**。若沒有此分頁，按右側 **»** 找到 Application。
7. 左側找到 **Storage（儲存空間）→ Cookies**，展開並選 **https://auth.riotgames.com**。
8. 右側表格找到 **Name（名稱）是 `ssid`** 的那一列。上方 Filter 可輸入 `ssid`。
9. 雙擊該列的 **Value（值）** 儲存格，複製完整值；不要複製名稱、整列、Expires 或 Domain。
10. 回終端機貼到 ssid 輸入處並按 Enter。輸入是隱藏的，畫面不會顯示字元，這是正常現象。

Firefox 使用 **F12 → Storage（儲存空間）→ Cookies → https://auth.riotgames.com**，其餘相同。

如果看不到 ssid：

- 確認當前分頁的網址是 `auth.riotgames.com`，不是 `playvalorant.com` 或 `account.riotgames.com`。
- 登入與 Cookie 檢視必須使用**同一個瀏覽器設定檔**，不能一邊一般視窗、一邊無痕視窗。
- 確認 2FA 已完成，再用精靈的登入連結重新登入。
- 若仍無此 Cookie，Windows 請改選 Riot Client 模式。不要拿其他 Cookie 假裝是 ssid。

ssid 等同登入憑證，只貼入本機精靈。Bot 會以它測試登入並加密保存；失效時需要重新登入。

若網址 token 驗證成功，但 ssid 顯示「工作階段失效／需要互動驗證」，代表兩種登入方式結果不同，不能保證只靠 ssid 就能自動更新。新版會在 ssid 失敗時提供切換到網址模式的選項；網址登入後，補填 ssid 失敗也會保留已成功的網址登入，讓你重試或留空暫時測試。只有 Cookie 更新實際成功後，才可用於無人值守排程；留空時 token 過期仍需手動登入。

## ssid 不足時：選 3，匯入 Riot 完整 Cookie

1. 在已登入的瀏覽器按 F12，選 **Network（網路）**，勾 **Preserve log（保留紀錄）**。
2. 重新開啟精靈顯示的 Riot 登入連結並完成所需驗證。
3. 在 Network 找到 **Request URL 是 `https://auth.riotgames.com/authorize?...`** 的請求；請求名稱通常是 `authorize`。
4. 點該請求 → **Headers → Request Headers**，複製 **Cookie** 欄位完整值，應包含 `ssid=...; ...`。
5. 精靈選 **3 Riot 完整 Cookie**，將值貼入隱藏輸入處。不是 Response Headers 的 Set-Cookie，也不是所有標頭。

這會保留該 Riot 網域的其他登入 Cookie，一併測試更新；Cookie 只會送至 `auth.riotgames.com`，並加密保存。此方式仍可能因失效、Riot 互動驗證或網路限制失敗，不保證永久登入。不要分享 Cookie 欄位或任何 token。

若回應 HTTP 406，先 `git pull --ff-only` 並重新啟動精靈。新版會讓 `/authorize` 網頁請求接受 HTML，而非只接受 JSON；userinfo／entitlement API 仍使用 JSON。若新版仍回報「HTTP 406（已使用網頁 Accept 標頭）」，表示此修正仍不足以解決當前環境，請只提供錯誤文字，不要持續重貼 Cookie 或分享憑證。

## 為什麼「正確網址」仍不能用？

一般遊戲首頁、Riot 帳號頁、原本的 authorize 連結，只是網頁位址，沒有 Bot 所需的登入 token。網址模式需要登入跳轉當下含 **`access_token`** 的完整網址，例如：

```text
https://playvalorant.com/opt_in#access_token=…&id_token=…&expires_in=3600
```

有些網頁會立即移除網址中的 token，因此即使你複製的是登入後的正確頁面，Bot 仍讀不到憑證。新版支援 `www`、語言路徑、結尾斜線及 token query／fragment，不再只接受單一 `/opt_in` 路徑。沒有 token 的網址仍不能用；此時改用 ssid 或 Riot Client 模式，不需要一直重複輸入帳密。

程式不會造訪貼上的任意網址取得憑證；解析出的 token 會交由 Riot 的 userinfo 與 entitlement 介面驗證。Cookie 登入則由 Riot authorize 的實際回應決定是否成功。

## 已跳轉到 404，而且網址包含 token

404 只代表最後那個網頁不存在，不能據此判定登入憑證失效。程式不會下載這個頁面；新版支援 Riot 官方驗證網域的 callback、路由 fragment 與整段 percent-encoded 網址。必須有 `access_token`；只有 `id_token` 或 `token_type` 仍不夠。

先更新並單獨診斷，不需重填 LINE 設定：

```bash
cd "$HOME/valbot"
git pull --ff-only
.venv/bin/python setup.py --check-browser-url
```

貼上網址時畫面不顯示字元是正常的。結果會指出是「網址解析」、「Riot 帳號驗證（userinfo）」或「Riot 遊戲授權（entitlement）」失敗，並顯示 HTTP 狀態碼；不會顯示 token，也不會改正式設定。若需協助，只分享錯誤訊息，不分享完整網址或 Cookie。
