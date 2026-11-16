import {isUsagePage, readUsagePage, toPayload} from "./usage-page.mjs";

const ALARM = "claude-usage-sync";
const HOST = "com.pcpcchen.smartscreen_claude";

async function badge(text, title) {
    await chrome.action.setBadgeText({text});
    await chrome.action.setTitle({title});
}

async function stop() {
    await chrome.alarms.clear(ALARM);
    await chrome.storage.session.remove("usageTab");
    await badge("", "SmartScreen · 在 Claude 用量頁點一下開始同步");
}

async function refreshFrom(tabId) {
    try {
        const tab = await chrome.tabs.get(tabId);
        if (!isUsagePage(tab.url)) return stop();
        const [{result}] = await chrome.scripting.executeScript({
            target: {tabId}, func: readUsagePage,
        });
        if ((await chrome.storage.session.get("usageTab")).usageTab !== tabId) return;
        if (!result) {
            await badge("…", "等待 Claude 用量頁的額度");
            return;
        }
        const response = await chrome.runtime.sendNativeMessage(HOST, toPayload(result));
        if (!response?.ok) throw new Error("Local import failed");
        await badge("ON", "Claude 用量已同步 · 點一下停止");
    } catch {
        await badge("!", "同步失敗 · 檢查本機橋接程式或 Claude 登入狀態");
    }
}

chrome.action.onClicked.addListener(async tab => {
    if (!isUsagePage(tab.url)) {
        if (!(await chrome.alarms.get(ALARM))) {
            await badge("?", "請在 https://claude.ai/settings/usage 頁面啟動同步");
        }
        return;
    }
    if ((await chrome.storage.session.get("usageTab")).usageTab === tab.id) {
        await stop();
        return;
    }
    await chrome.storage.session.set({usageTab: tab.id});
    await chrome.alarms.create(ALARM, {periodInMinutes: 1});
    await refreshFrom(tab.id);
});

chrome.alarms.onAlarm.addListener(async alarm => {
    if (alarm.name !== ALARM) return;
    const {usageTab: tabId} = await chrome.storage.session.get("usageTab");
    if (tabId === undefined) return stop();
    try {
        const tab = await chrome.tabs.get(tabId);
        if (!isUsagePage(tab.url)) return stop();
        if (tab.status !== "loading") await chrome.tabs.reload(tabId);
    } catch {
        await stop();
    }
});

chrome.tabs.onUpdated.addListener(async (tabId, change) => {
    if (change.status !== "complete") return;
    if ((await chrome.storage.session.get("usageTab")).usageTab === tabId) await refreshFrom(tabId);
});

chrome.tabs.onRemoved.addListener(async tabId => {
    if ((await chrome.storage.session.get("usageTab")).usageTab === tabId) await stop();
});
