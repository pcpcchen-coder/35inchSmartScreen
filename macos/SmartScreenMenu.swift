import AppKit

private struct MenuState: Decodable, Equatable {
    let enabled: Bool
    let mode: String
    let poll_seconds: Int
    let page_seconds: Int
    let brightness: Int?
    let blank_on_stop: Bool
}

private struct Service {
    let python: URL
    let resources: URL
    let dashboardRoot: String
    let dashboardPython: String

    func run(_ arguments: [String]) throws -> Data {
        let process = Process()
        process.executableURL = python
        process.arguments = [
            "-B", resources.appendingPathComponent("service.py").path,
            "--dashboard-root", dashboardRoot, "--dashboard-python", dashboardPython,
        ] + arguments
        process.currentDirectoryURL = resources
        let output = Pipe()
        process.standardOutput = output
        process.standardError = output
        try process.run()
        let data = output.fileHandleForReading.readDataToEndOfFile()
        process.waitUntilExit()
        if process.terminationStatus != 0 {
            let details = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
            throw NSError(domain: "SmartScreen", code: Int(process.terminationStatus), userInfo: [
                NSLocalizedDescriptionKey: details.isEmpty ? "背景服務指令執行失敗。" : details
            ])
        }
        return data
    }
}

private final class MenuController: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private let statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
    private let menu = NSMenu()
    private let service: Service
    private var busy = false
    private var reading = false
    private var state: MenuState?

    init(service: Service) {
        self.service = service
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        let icon = NSImage(systemSymbolName: "display", accessibilityDescription: "SmartScreen 小螢幕")
        icon?.isTemplate = true
        statusItem.button?.image = icon
        if icon == nil {
            statusItem.button?.title = "▣"
        }
        statusItem.autosaveName = "SmartScreen"
        statusItem.button?.setAccessibilityLabel("SmartScreen 小螢幕")
        statusItem.button?.toolTip = "SmartScreen 小螢幕"
        menu.autoenablesItems = false
        menu.delegate = self
        statusItem.menu = menu
        refreshState()
    }

    func menuWillOpen(_ menu: NSMenu) {
        refreshState()
        buildMenu()
    }

    private func refreshState() {
        guard !busy, !reading else { return }
        reading = true
        let service = service
        DispatchQueue.global(qos: .userInitiated).async {
            let updated = try? JSONDecoder().decode(MenuState.self, from: service.run(["menu-status"]))
            DispatchQueue.main.async {
                self.reading = false
                if self.state != updated || self.menu.items.isEmpty {
                    self.state = updated
                    self.buildMenu()
                    let hasIcon = self.statusItem.button?.image != nil || self.statusItem.button?.title == "▣"
                    let message = "SmartScreen menu (visible=\(self.statusItem.isVisible), icon=\(hasIcon), items=\(self.menu.items.count))\n"
                    FileHandle.standardError.write(Data(message.utf8))
                }
            }
        }
    }

    private func buildMenu() {
        menu.removeAllItems()
        if busy {
            menu.addItem(item("正在套用設定…"))
            return
        }

        if let state {
            buildControls(state)
        } else {
            menu.addItem(item(reading ? "正在讀取面板狀態…" : "無法讀取面板狀態"))
        }
        menu.addItem(.separator())
        menu.addItem(item("開啟診斷記錄", action: #selector(openLog)))
        menu.addItem(item("結束選單列工具", action: #selector(quit)))
    }

    private func buildControls(_ state: MenuState) {
        menu.addItem(item(state.enabled ? "SmartScreen · 面板已啟用" : "SmartScreen · 面板已停止"))
        let toggleTitle = state.enabled ? "停止面板（取消登入啟動）" : "啟動面板（登入自動啟動）"
        menu.addItem(command(toggleTitle, [state.enabled ? "uninstall" : "install"]))
        let refresh = command("立即同步 ChatGPT", ["refresh"])
        refresh.isEnabled = state.enabled && state.mode != "claude"
        menu.addItem(refresh)
        menu.addItem(.separator())

        menu.addItem(choices("顯示內容", key: "mode", selected: state.mode, options: [
            ("ChatGPT 與 Claude 輪播", "rotate"),
            ("只顯示 ChatGPT", "chatgpt"),
            ("只顯示 Claude", "claude"),
        ]))
        let polling = choices("ChatGPT 同步間隔", key: "poll_seconds", selected: String(state.poll_seconds),
                              options: seconds([15, 30, 60, 120]))
        polling.isEnabled = state.mode != "claude"
        menu.addItem(polling)

        let rotation = choices("頁面輪播間隔", key: "page_seconds", selected: String(state.page_seconds),
                               options: seconds([10, 20, 30, 60]))
        rotation.isEnabled = state.mode == "rotate"
        menu.addItem(rotation)

        let brightness = choices(state.brightness == nil ? "螢幕亮度（裝置預設）" : "螢幕亮度",
                                 key: "brightness", selected: state.brightness.map(String.init),
                                 options: [20, 40, 60, 80, 100].map { ("\($0)%", String($0)) })
        menu.addItem(brightness)

        let blank = command("停止面板時熄屏", ["set", "blank_on_stop", String(!state.blank_on_stop)])
        blank.state = state.blank_on_stop ? .on : .off
        menu.addItem(blank)
    }

    private func item(_ title: String, action: Selector? = nil) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: "")
        item.target = self
        item.isEnabled = action != nil
        return item
    }

    private func command(_ title: String, _ arguments: [String]) -> NSMenuItem {
        let item = item(title, action: #selector(runCommand(_:)))
        item.representedObject = arguments
        return item
    }

    private func seconds(_ values: [Int]) -> [(String, String)] {
        values.map { ("\($0) 秒", String($0)) }
    }

    private func choices(_ title: String, key: String, selected: String?, options: [(String, String)]) -> NSMenuItem {
        let parent = item(title)
        parent.isEnabled = true
        let submenu = NSMenu(title: title)
        submenu.autoenablesItems = false
        for (label, value) in options {
            let option = command(label, ["set", key, value])
            option.state = value == selected ? .on : .off
            submenu.addItem(option)
        }
        parent.submenu = submenu
        return parent
    }

    @objc private func runCommand(_ sender: NSMenuItem) {
        guard !busy, let arguments = sender.representedObject as? [String] else { return }
        busy = true
        let service = service
        DispatchQueue.global(qos: .userInitiated).async {
            let result = Result { try service.run(arguments) }
            DispatchQueue.main.async {
                self.busy = false
                self.refreshState()
                if case .failure(let error) = result {
                    self.showError(error.localizedDescription)
                }
            }
        }
    }

    @objc private func openLog() {
        let log = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/35inchSmartScreen/dashboard.log")
        if !NSWorkspace.shared.open(log) {
            showError("目前找不到面板記錄。")
        }
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    private func showError(_ details: String) {
        let alert = NSAlert()
        alert.messageText = "SmartScreen"
        alert.informativeText = details
        NSApp.activate(ignoringOtherApps: true)
        alert.runModal()
    }
}

guard
    let python = Bundle.main.object(forInfoDictionaryKey: "SmartScreenPython") as? String,
    let root = Bundle.main.object(forInfoDictionaryKey: "SmartScreenRoot") as? String,
    let dashboardPython = Bundle.main.object(forInfoDictionaryKey: "SmartScreenDashboardPython") as? String,
    let resources = Bundle.main.resourceURL
else {
    fputs("Install SmartScreen with install_menu.py.\n", stderr)
    exit(1)
}
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
private let controller = MenuController(service: Service(
    python: URL(fileURLWithPath: python), resources: resources,
    dashboardRoot: root, dashboardPython: dashboardPython
))
app.delegate = controller
app.run()
