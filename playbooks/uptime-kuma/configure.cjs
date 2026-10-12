// Uses the pinned Kuma image's Socket.IO client; no host/npm dependencies.
const { isDeepStrictEqual } = require("node:util");

function named(items, kind) {
    const result = new Map();
    for (const item of items) {
        if (!item.name || result.has(item.name)) {
            throw new Error(`Missing or duplicate ${kind} name`);
        }
        result.set(item.name, item);
    }
    return result;
}

function validate(config) {
    const notifications = named(config.notifications, "notification");
    named(config.monitors, "monitor");
    for (const n of config.notifications) {
        if (n.type !== "telegram" || !n.telegramBotToken || !n.telegramChatID) {
            throw new Error("Only Telegram notifications with token/chat ID are supported");
        }
    }
    for (const m of config.monitors) {
        // HTTP-only export. Add explicit type-specific payloads before adding other types.
        if (m.type !== "http" || !/^https?:\/\//.test(m.url) || m.parent != null || m.proxyId != null) {
            throw new Error("Only ungrouped HTTP monitors without a monitor proxy are supported");
        }
        if (!Array.isArray(m.notifications) || m.notifications.some(n => !notifications.has(n))) {
            throw new Error("Monitor refers to an undeclared notification");
        }
    }
}

function differs(current, desired) {
    return Object.entries(desired).some(([key, value]) => !isDeepStrictEqual(current[key], value));
}

function enabledNotifications(list) {
    return Object.fromEntries(Object.entries(list || {}).filter(([, enabled]) => enabled).map(([id]) => [id, true]));
}

async function reconcile(call, config, state) {
    validate(config);
    // Preflight duplicate names before any writes. Unlisted objects are never deleted.
    const notifications = named(state.notifications, "existing notification");
    const monitors = named(Object.values(state.monitors), "existing monitor");
    for (const m of config.monitors) {
        if (monitors.has(m.name) && monitors.get(m.name).type !== "http") {
            throw new Error("Existing managed monitor is not HTTP; refusing type conversion");
        }
    }
    const actions = [];
    const notificationIDs = new Map();
    const currentSettings = (await call("getSettings")).data;
    if (differs(currentSettings, config.settings)) {
        actions.push("settings: update");
        if (!config.check) {
            await call("setSettings", { ...currentSettings, ...config.settings }, config.password);
        }
    }
    for (const desired of config.notifications) {
        const current = notifications.get(desired.name);
        const currentConfig = current ? JSON.parse(current.config) : {};
        let id = current?.id;
        if (!current || differs(currentConfig, desired)) {
            actions.push(`notification: ${desired.name} (${current ? "update" : "create"})`);
            if (!config.check) {
                const saved = await call("addNotification", { ...currentConfig, ...desired, applyExisting: false }, id || null);
                id = saved.id;
            }
        }
        notificationIDs.set(desired.name, id || `new:${desired.name}`);
    }
    for (const specification of config.monitors) {
        const { notifications: assignments, active, ...desired } = specification;
        desired.notificationIDList = Object.fromEntries(assignments.map(name => [notificationIDs.get(name), true]));
        const existing = monitors.get(desired.name);
        const current = existing ? (await call("getMonitor", existing.id)).monitor : null;
        if (current) {
            current.notificationIDList = enabledNotifications(current.notificationIDList);
        }
        let id = existing?.id;
        if (!current || differs(current, desired)) {
            actions.push(`monitor: ${desired.name} (${current ? "update" : "create"})`);
            if (!config.check) {
                const payload = {
                    // Null/default fields required by Kuma's HTTP monitor add/validate path.
                    headers: null, body: null, basic_auth_user: null, basic_auth_pass: null,
                    tlsCa: null, tlsCert: null, tlsKey: null,
                    ...current, ...desired,
                };
                const saved = await call(current ? "editMonitor" : "add", payload);
                id = saved.monitorID;
            }
        }
        // New monitors start active. Existing monitors keep their database active state on edit.
        if (Boolean(current ? current.active : true) !== active) {
            actions.push(`monitor: ${desired.name} (${active ? "resume" : "pause"})`);
            if (!config.check) {
                await call(active ? "resumeMonitor" : "pauseMonitor", id);
            }
        }
    }
    return { changed: actions.length > 0, actions };
}

async function main() {
    const fs = require("node:fs");
    const config = JSON.parse(fs.readFileSync(0, "utf8"));
    validate(config);
    if (!config.username || !config.password) {
        throw new Error("Set AUTH_PASS in external_vars.yml");
    }
    if (require("/app/package.json").version !== "2.5.6") {
        throw new Error("Configuration API is pinned to Kuma 2.5.6; deploy that version first");
    }
    const { io } = require("socket.io-client");
    const socket = io("http://127.0.0.1:3001", {
        transports: ["websocket"], reconnection: false, autoConnect: false, timeout: 10000,
    });
    const state = { notifications: null, monitors: null };
    socket.on("notificationList", list => { state.notifications = list; });
    socket.on("monitorList", list => { state.monitors = list; });
    const call = (event, ...args) => new Promise((resolve, reject) => {
        socket.timeout(30000).emit(event, ...args, (error, result) => {
            // API errors can include credentials. Never echo response bodies or tokens.
            if (error || (event !== "needSetup" && !result?.ok)) {
                reject(new Error(`Kuma ${event} failed; inspect server diagnostics privately`));
            } else {
                resolve(result);
            }
        });
    });
    try {
        await new Promise((resolve, reject) => {
            const timer = setTimeout(() => reject(new Error("Cannot connect to Kuma")), 15000);
            // Kuma awaits sendInfo before registering API handlers; connect is too early.
            socket.once("info", () => { clearTimeout(timer); resolve(); });
            socket.once("connect_error", () => {
                clearTimeout(timer);
                reject(new Error("Cannot connect to Kuma"));
            });
            socket.connect();
        });
        let createdAccount = false;
        if (await call("needSetup")) {
            if (config.check) {
                const actions = ["account: create", "settings: initialize",
                    ...config.notifications.map(n => `notification: ${n.name} (create)`),
                    ...config.monitors.map(m => `monitor: ${m.name} (create)`)];
                console.log(JSON.stringify({ changed: true, actions }));
                return;
            }
            await call("setup", config.username, config.password);
            createdAccount = true;
        }
        await call("login", { username: config.username, password: config.password });
        // afterLogin emits both lists before acknowledging the login.
        if (state.notifications === null || state.monitors === null) {
            throw new Error("Kuma did not send configuration lists");
        }
        const result = await reconcile(call, config, state);
        if (createdAccount) {
            result.actions.unshift("account: create");
            result.changed = true;
        }
        console.log(JSON.stringify(result));
    } finally {
        socket.disconnect();
    }
}

module.exports = { reconcile, validate };
if (!module.parent) {
    main().catch(error => {
        // Only our own credential-free messages are exposed; unexpected exceptions are redacted.
        console.error(error.message.startsWith("Kuma ") || error.message.startsWith("Set AUTH_PASS") ||
            error.message.startsWith("Configuration API") || error.message === "Cannot connect to Kuma" ?
            error.message : "Configuration failed; inspect input and server diagnostics privately");
        process.exitCode = 1;
    });
}
