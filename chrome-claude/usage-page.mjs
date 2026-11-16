export function isUsagePage(url) {
    if (!url) return false;
    const page = new URL(url);
    return page.origin === "https://claude.ai" &&
        (page.pathname === "/settings/usage" || page.hash === "#settings/usage");
}

// Chrome serializes this function into the chosen tab.
export async function readUsagePage() {
    if (location.origin !== "https://claude.ai" ||
        (location.pathname !== "/settings/usage" && location.hash !== "#settings/usage")) return null;

    const labels = new Map([
        ["目前工作階段", "five_hour"], ["Current session", "five_hour"],
        ["本週", "seven_day"], ["This week", "seven_day"], ["All models", "seven_day"],
    ]);
    for (let attempt = 0; attempt < 24; attempt++) {
        const result = {};
        for (const meter of document.querySelectorAll('[role="meter"][aria-valuenow]')) {
            if (meter.getBoundingClientRect().width === 0) continue;
            const id = meter.getAttribute("aria-labelledby");
            const name = (meter.getAttribute("aria-label") ||
                (id && document.getElementById(id)?.innerText.split("\n")[0]))?.trim();
            const key = labels.get(name);
            if (!key) continue;

            const value = meter.getAttribute("aria-valuenow");
            const used = Number(value);
            if (value === "" || !Number.isFinite(used) || used < 0 || used > 100) continue;

            let row = meter.parentElement;
            for (let depth = 0; depth < 5 && row; depth++, row = row.parentElement) {
                if (row.querySelectorAll('[role="meter"]').length !== 1) break;
                const reset = row.innerText.split("\n").map(line => line.trim()).find(line =>
                    /^(?:Resets?\b|(?:[星期週禮拜]+[日一二三四五六天]|今天|明天).*重[設置]|從您的第一則訊息開始)/i.test(line));
                if (reset) {
                    result[key] = {used, reset};
                    break;
                }
            }
        }
        if ("seven_day" in result) return result;
        await new Promise(resolve => setTimeout(resolve, 300));
    }
    return null;
}

const zhDays = {"日": 0, "天": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6};
const enDays = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

export function resetTimestamp(text, now, windowHours) {
    const zh = text.match(/^(星期|週|禮拜)?([日一二三四五六天]|今天|明天)\s*(上午|下午)?\s*(\d{1,2}):(\d{2})\s*重[設置]$/);
    const en = text.match(/^Resets?\s+(?:on\s+)?(today|tomorrow|Sun\w*|Mon\w*|Tue\w*|Wed\w*|Thu\w*|Fri\w*|Sat\w*)[\s,]*(?:at\s+)?(\d{1,2}):(\d{2})\s*(AM|PM)?$/i);
    const relative = text.match(/^Resets? in\s+(?:(\d+)\s*(?:hr?s?|hours?)\s*)?(?:(\d+)\s*(?:m(?:ins?)?|minutes?))?$/i);
    if (relative && (relative[1] || relative[2])) {
        const hours = Number(relative[1] || 0) + Number(relative[2] || 0) / 60;
        return hours <= windowHours ? Math.floor(now.getTime() / 1000 + hours * 3600) : null;
    }
    if (!zh && !en) return null;
    const day = zh ? zh[2] : en[1].toLowerCase();
    const period = zh ? zh[3] : en[4]?.toUpperCase();
    let hours = Number(zh ? zh[4] : en[2]);
    const minutes = Number(zh ? zh[5] : en[3]);
    if (hours > 23 || minutes > 59 || (period && (hours < 1 || hours > 12))) return null;
    if (period) hours = hours % 12 + (period === "下午" || period === "PM" ? 12 : 0);
    const relativeDay = ["today", "今天"].includes(day) ? 0 : ["tomorrow", "明天"].includes(day) ? 1 : null;
    const weekday = zh ? zhDays[day] : enDays.indexOf(day.slice(0, 3));
    const target = new Date(now);
    target.setHours(hours, minutes, 0, 0);
    const days = relativeDay ?? ((weekday - now.getDay() + 7) % 7);
    target.setDate(target.getDate() + days);
    if (relativeDay === null && target <= now) target.setDate(target.getDate() + 7);
    const delay = target - now;
    return delay > 0 && delay <= (windowHours * 60 + 1) * 60_000 ? Math.floor(target.getTime() / 1000) : null;
}

export function toPayload(snapshot, now = new Date()) {
    const rate_limits = {};
    for (const [key, hours] of [["five_hour", 5], ["seven_day", 168]]) {
        const window = snapshot?.[key];
        if (!window) continue;
        rate_limits[key] = {
            used_percentage: window.used,
            resets_at: resetTimestamp(window.reset, now, hours),
        };
    }
    return {rate_limits};
}
