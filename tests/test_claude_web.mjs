import assert from "node:assert/strict";
import test from "node:test";
import {isUsagePage, readUsagePage, toPayload} from "../chrome-claude/usage-page.mjs";

test("only the official Claude usage location is accepted", () => {
    assert.equal(isUsagePage("https://claude.ai/settings/usage"), true);
    assert.equal(isUsagePage("https://claude.ai/new#settings/usage"), true);
    assert.equal(isUsagePage("https://claude.ai/chat/example"), false);
    assert.equal(isUsagePage("https://example.test/#settings/usage"), false);
});

test("renders weekday reset text as a local timestamp without inventing missing resets", () => {
    const now = new Date(2026, 10, 16, 21, 45);
    const payload = toPayload({
        five_hour: {used: 12, reset: "週二上午1:30 重設"},
        seven_day: {used: 27, reset: "星期四上午11:00 重設"},
    }, now);
    assert.deepEqual(payload.rate_limits, {
        five_hour: {used_percentage: 12, resets_at: new Date(2026, 10, 17, 1, 30).getTime() / 1000},
        seven_day: {used_percentage: 27, resets_at: new Date(2026, 10, 19, 11).getTime() / 1000},
    });
    assert.deepEqual(toPayload({
        five_hour: {used: 0, reset: "從您的第一則訊息開始"},
        seven_day: {used: 23, reset: "Resets Thursday at 11:00 AM"},
    }, now).rate_limits, {
        five_hour: {used_percentage: 0, resets_at: null, idle: true},
        seven_day: {used_percentage: 23, resets_at: new Date(2026, 10, 19, 11).getTime() / 1000},
    });
});

test("reads quota meters and ignores product breakdown meters", async () => {
    const names = {session: "目前工作階段", week: "本週\n▾", product: "Claude Code"};
    function meter(id, value, reset) {
        return {
            getAttribute: key => ({"aria-labelledby": id, "aria-valuenow": value})[key],
            getBoundingClientRect: () => ({width: 100}),
            parentElement: {
                querySelectorAll: () => [1],
                innerText: reset,
            },
        };
    }

    globalThis.location = new URL("https://claude.ai/new#settings/usage");
    globalThis.document = {
        getElementById: id => ({innerText: names[id]}),
        querySelectorAll: () => [
            meter("session", "9", "於 上午11:40 重設"),
            meter("week", "29", "星期四上午11:00 重設"),
            meter("product", "99", "星期四上午11:00 重設"),
        ],
    };
    try {
        assert.deepEqual(await readUsagePage(), {
            five_hour: {used: 9, reset: "於 上午11:40 重設"},
            seven_day: {used: 29, reset: "星期四上午11:00 重設"},
        });
    } finally {
        delete globalThis.document;
        delete globalThis.location;
    }
});

test("reads the same-day Chinese format and preserves quota when the time is unknown", () => {
    const today = new Date(2026, 10, 17, 6, 55);
    const reset = new Date(2026, 10, 17, 11, 40).getTime() / 1000;
    assert.deepEqual(toPayload({five_hour: {used: 9, reset: "於 上午11:40 重設"}}, today).rate_limits,
        {five_hour: {used_percentage: 9, resets_at: reset}});
    assert.deepEqual(toPayload({five_hour: {used: 0, reset: null}}, today).rate_limits,
        {five_hour: {used_percentage: 0, resets_at: null, idle: false}});
});
