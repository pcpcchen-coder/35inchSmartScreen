# TURZX 3.5 吋 ChatGPT 用量面板

用 Mac 把 ChatGPT 的 Work／Codex 用量送到 TURZX 3.5 吋 USB 小螢幕。畫面使用直向 320 × 480 解析度。

![示意圖，使用範例數字](docs/preview.png)

## 畫面顯示

- **剩餘額度**依帳號實際回傳的週期顯示，例如 5 小時與每週剩餘百分比，以及距離重設的時間。
- **最近 7 天 token 用量**顯示每日長條與總計。圖表按 UTC 日期排列，包含今天。
- **最後同步時間**以 Mac 的本地時間顯示。預設每 30 秒向 Codex App Server 查詢一次，最新用量以服務端回傳為準。重設倒數在本機更新。
- **LIVE** 表示兩項資料都已取得。**PARTIAL** 表示其中一項查詢失敗。**STALE** 顯示先前取得的資料，**OFFLINE** 表示兩項資料都還未取得。

額度來自 Work／Codex 共用用量，token 圖使用 App Server 的帳號統計。一般 Chat 的模型訊息上限和 OpenAI API 帳單有各自的用量來源。程式使用 Codex 既有的 ChatGPT 登入，只查詢用量，不會發送模型請求，也不會把用量存進檔案或 GitHub。

## 安裝與試跑

需要 macOS、Python 3.11 以上、libusb、支援用量查詢的 Codex CLI，以及已透過 ChatGPT 帳號登入的 Codex。程式會先找 PATH 上的 `codex`，再找 `/Applications/ChatGPT.app` 內建的 CLI。

1. 把 TURZX 3.5 吋螢幕接到 Mac 的 USB 資料埠。已實測的裝置是 Turing `UsbMonitor`、VID/PID `1a86:5722`、序號 `USB35INCHIPSV2`。
2. 下載程式並建立 Python 環境。

   ```sh
   brew install libusb
   git clone https://github.com/pcpcchen-coder/35inchSmartScreen.git
   cd 35inchSmartScreen
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```

3. 查詢一次並送到螢幕。確認硬體畫面後，移除 `--once` 就會持續刷新。

   ```sh
   .venv/bin/python dashboard.py --once
   .venv/bin/python dashboard.py
   ```

可以用 `--interval 60` 調整查詢間隔，或以 `--port /dev/cu.usbmodem…` 依 USB 位置指定裝置。畫面透過 USB bulk 直接傳輸。拔掉螢幕後，背景程式會在 USB 裝置重新出現時重連。

只想預覽版面時，用以下指令產生範例 PNG。這個模式不會查詢帳號或使用 USB。

```sh
.venv/bin/python dashboard.py --preview preview.png
```

## 登入後自動啟動

結束前景測試後，執行下列指令。服務會立即啟動，之後在同一位 macOS 使用者登入時自動啟動。

```sh
.venv/bin/python service.py install
.venv/bin/python service.py status
tail -n 30 ~/Library/Logs/35inchSmartScreen/dashboard.log
```

要停止服務並取消自動啟動，執行 `.venv/bin/python service.py uninstall`。程式資料夾移動後，請從新位置重新執行安裝。

## 畫面出現橫線或亂碼

從舊版升級時，更新 Python 相依套件，然後重新啟動背景服務。若仍有殘留亂碼，拔掉這台小螢幕的 USB 再插回，讓螢幕重新初始化。

```sh
brew install libusb
git pull --ff-only
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python service.py install
```

## 參考資料

- [Codex App Server 用量與額度介面](https://learn.chatgpt.com/docs/app-server#6-rate-limits-chatgpt)
- [OpenAI Work／Codex 用量說明](https://help.openai.com/en/articles/20001516-managing-usage-with-gpt-6-astra-in-work-and-codex)
- [Turing Smart Screen 3.5 吋硬體識別](https://github.com/mathoudebine/turing-smart-screen-python/wiki/Hardware-revisions#turing-smart-screen-35)
- [TURZX Rev. A 序列埠協定參考](https://github.com/mathoudebine/turing-smart-screen-python/blob/main/library/lcd/lcd_comm_rev_a.py)
- [macOS 花屏與 USB bulk 傳輸驗證](https://github.com/mathoudebine/turing-smart-screen-python/issues/7)
