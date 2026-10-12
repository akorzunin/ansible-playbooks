const test = require("node:test");
const assert = require("node:assert/strict");
const { reconcile } = require("./configure.cjs");

function fixture() {
    const notification = { name: "Telegram", type: "telegram", isDefault: false,
        telegramBotToken: "test-secret", telegramChatID: "42", telegramSendSilently: true };
    const monitor = { name: "workstation", type: "http", url: "https://example.com/",
        interval: 600, active: true, notifications: ["Telegram"] };
    const config = { password: "test-password", settings: { keepDataPeriodDays: 180 },
        notifications: [notification], monitors: [monitor], check: false };
    const state = { notifications: [], monitors: {} };
    const settings = { disableAuth: false, otherSetting: "preserve" };
    const calls = [];
    async function call(event, ...args) {
        calls.push({ event, args: structuredClone(args) });
        if (event === "getSettings") return { data: structuredClone(settings) };
        if (event === "setSettings") Object.assign(settings, args[0]);
        if (event === "addNotification") {
            const id = args[1] || 7;
            state.notifications = [{ id, name: args[0].name, config: JSON.stringify(args[0]) }];
            return { id };
        }
        if (event === "getMonitor") return { monitor: structuredClone(state.monitors[args[0]]) };
        if (event === "add" || event === "editMonitor") {
            const id = args[0].id || 9;
            state.monitors[id] = { active: true, ...args[0], id };
            return { monitorID: id };
        }
        if (event === "pauseMonitor" || event === "resumeMonitor") {
            state.monitors[args[0]].active = event === "resumeMonitor";
        }
        return { ok: true };
    }
    return { config, state, settings, calls, call };
}

const writes = f => f.calls.filter(c => !["getSettings", "getMonitor"].includes(c.event));

test("creates notification first, remaps IDs, merges settings, then is idempotent", async () => {
    const f = fixture();
    assert.equal((await reconcile(f.call, f.config, f.state)).changed, true);
    assert.deepEqual(f.state.monitors[9].notificationIDList, { 7: true });
    assert.equal(f.settings.otherSetting, "preserve");
    assert.equal(f.settings.disableAuth, false);
    assert.deepEqual(writes(f).map(c => c.event), ["setSettings", "addNotification", "add"]);
    f.calls.length = 0;
    assert.deepEqual(await reconcile(f.call, f.config, f.state), { changed: false, actions: [] });
    assert.equal(writes(f).length, 0);
});

test("check mode reports changes without any writes or credentials in summary", async () => {
    const f = fixture();
    f.config.check = true;
    const result = await reconcile(f.call, f.config, f.state);
    assert.equal(result.changed, true);
    assert.equal(writes(f).length, 0);
    assert.equal(JSON.stringify(result).includes("test-secret"), false);
    assert.equal(JSON.stringify(result).includes("test-password"), false);
});

test("edits in place and preserves unmanaged fields, objects and history IDs", async () => {
    const f = fixture();
    await reconcile(f.call, f.config, f.state);
    f.state.monitors[9].headers = '{"X-Custom":"preserve"}';
    f.state.monitors[10] = { id: 10, name: "unmanaged", type: "http" };
    f.config.monitors[0].interval = 300;
    f.config.notifications[0].telegramSendSilently = false;
    f.calls.length = 0;
    await reconcile(f.call, f.config, f.state);
    assert.deepEqual(writes(f).map(c => c.event), ["addNotification", "editMonitor"]);
    assert.equal(f.state.monitors[9].headers, '{"X-Custom":"preserve"}');
    assert.equal(f.state.monitors[10].name, "unmanaged");
});

test("pauses and resumes only when active state differs", async () => {
    const f = fixture();
    f.config.monitors[0].active = false;
    await reconcile(f.call, f.config, f.state);
    assert.equal(f.state.monitors[9].active, false);
    f.calls.length = 0;
    assert.equal((await reconcile(f.call, f.config, f.state)).changed, false);
    f.config.monitors[0].active = true;
    await reconcile(f.call, f.config, f.state);
    assert.equal(f.state.monitors[9].active, true);
    assert.deepEqual(writes(f).map(c => c.event), ["resumeMonitor"]);
});

test("undeclared notifications, duplicate names and incompatible types fail before writes", async () => {
    for (const mutate of [
        f => { f.config.monitors[0].notifications = ["missing"]; },
        f => { f.config.monitors.push(structuredClone(f.config.monitors[0])); },
        f => { f.state.notifications = [{ name: "duplicate" }, { name: "duplicate" }]; },
        f => { f.state.monitors[1] = { name: "workstation", type: "ping" }; },
    ]) {
        const f = fixture();
        mutate(f);
        await assert.rejects(reconcile(f.call, f.config, f.state));
        assert.equal(writes(f).length, 0);
    }
});
