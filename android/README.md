# VALORA Android

直接下載：[VALORA-1.0.0.apk](https://github.com/PearcePin/valbot/releases/download/android-v1.0.0/VALORA-1.0.0.apk)

## 安裝

1. 用 Android 手機下載 APK，點開檔案。
2. Android 若詢問，允許這個瀏覽器／檔案管理員「安裝未知應用程式」。
3. 安裝後開啟 **VALORA** →「連結我的 Riot 帳號」。
4. 台灣帳號選 AP，在 Riot 網頁完成帳密、2FA 或驗證。成功後 App 自動接回登入，不需要手動貼網址／Cookie。
5. 不需要 LINE Token、公開網址、Cloudflare 或持續開著 Ubuntu。手機直接查詢 Riot 與公開圖庫。

最低 Android 8.0，APK 同時包含 arm64、32 位元 ARM、x86_64。建議先更新 Android System WebView／Chrome。

## 功能

- 商店、夜市、配件、精選組合包、VP／RP／KC 錢包；造型圖片區使用稀有度色背景。
- 每頁 10 場的詳細戰績，可持續翻頁；原有 ACS、ADR、爆頭比例、多殺、經濟等分析。
- 本季段位、RR、勝率、定級進度、近期 RR 變動與賽季紀錄。
- 手動好友狀態、選人私訊、輸入內容及送出前確認。
- 手動短暫收信與本機訊息列表，可選好友回覆；沒有常駐好友連線或自動上線提醒。
- 在「我的」可開啟每日 08:05（台灣時間）商店通知。Android 13+ 需允許通知；Doze、省電及網路限制可能延後，不能保證精準 08:05。

## 登入的實際限制

App 將 Riot 的 token／Cookie 留在這支手機，用 Android Keystore AES-GCM 加密，不保存密碼。一般 token 到期先嘗試更新，不必重新輸入 Cookie；需要互動驗證時，直接在 App 的 Riot 網頁繼續。

**換成 APK 不能讓 Riot 的登入永久有效。** Riot 撤銷 Cookie、要求 2FA／CAPTCHA 或拒絕嵌入式 WebView 時仍可能失敗；本版本是個人測試版，不能宣稱已用真實帳號實測成功。登入頁沒有 JavaScript 原生橋接，App 不讀取密碼欄位。第一次使用請在自己的手機驗證登入、資料、私訊送達與通知。

「已提交私訊」不是送達／已讀回條；手動收信無法保證補回離線或已送往其他 Client 的完整聊天。移除 App 會失去本機訊息、草稿及登入；同簽章升級 APK 可保留。

## 建置與簽章

`.github/workflows/android.yml` 使用 JDK 17、Gradle 8.13、AGP 8.9.2、Chaquopy 17.1、Python 3.11 與 Android SDK 35。Python 僅安裝 httpx／portalocker，重用根目錄 `valbot` 的服務與圖卡，不內嵌任何 LINE／Riot 帳號資料。

GitHub Actions 使用儲存庫加密 Secrets 的專用 PKCS12 金鑰簽署 APK，並驗證簽章。金鑰不進 Git；這台開發主機的 `.android-tools/valora-signing.p12` 與密碼檔也需私下備份，不能分享或提交。後續版本須沿用同一金鑰及 applicationId，並提高 versionCode，才能直接覆蓋更新保留資料。

本機 Windows 可先用 `python android/bootstrap_tools.py` 準備工具；以 `.android-tools` 的 JDK 17／Gradle 設定 JAVA_HOME、ANDROID_HOME，並設定 `VALBOT_BUILD_PYTHON` 指向 Python 3.11，再在 android 目錄執行 `gradle assembleRelease`。未提供正式簽章環境變數時只會產生測試簽章 APK，不要拿它覆蓋正式簽章版本。

驗證分為 Python 邏輯測試、APK 編譯與簽章、Android 模擬器啟動測試。這些都不能替代真實 Riot 登入及私訊送達測試。
