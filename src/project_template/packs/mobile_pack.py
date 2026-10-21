#!/usr/bin/env python3
"""Mobile app add-on (`--with mobile`): Expo (React Native + TypeScript) for Android and iOS.

Purpose:
    One TypeScript code base for both phones, in `mobile/`, laid out in the same layers as
    the rest of the template so the comment, layer and logging checks apply unchanged:
      - `mobile/src/config/`      : `env.ts` (only place that reads `process.env`), `logger.ts`
      - `mobile/src/domain/`      : plain types, no I/O
      - `mobile/src/services/`    : pure logic (unit-tested with `node --test`, no install needed)
      - `mobile/src/adapters/`    : HTTP client for the backend (timeout + logging)
      - `mobile/src/entrypoints/` : `App.tsx` screens
      - `mobile/test/*.test.ts`   : Node's built-in runner executes TypeScript directly
    Tools are project-local dev dependencies (`pnpm exec expo ...`); `@expo/ngrok` is local
    too, so `--tunnel` never installs anything globally.

Running (see the generated `mobile/MOBILE.md`):
    Default: iOS Simulator / Android emulator — both reach the Mac at 127.0.0.1, so the
    "local services bind 127.0.0.1 only" rule stays intact. Real phone: `expo start --tunnel`
    only; the Python backend is never opened to the network.

Versions:
    `EXPO_SDK` pins the Expo SDK; after raising it run `pnpm exec expo install --fix`
    in `mobile/` so react / react-native / typescript match that SDK.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from project_template.packs.common import NPM_BLOCK_ENGINES, npm_slug
from project_template.packs.common import write_file as _write

EXPO_SDK = "58"
DEPENDENCIES = {"expo": "~58.0.16", "expo-status-bar": "~58.0.3", "react": "19.3.0", "react-native": "0.88.0"}
# @types/node: the tests use node:test / node:assert (matches the Node major in .nvmrc)
DEV_DEPENDENCIES = {"@expo/ngrok": "^4.1.3", "@types/node": "^24.19.2", "@types/react": "~19.3.0", "typescript": "~6.0.3"}
MOBILE_TEST = "(cd mobile && node --test)"
MOBILE_TYPECHECK = "(cd mobile && pnpm exec tsc --noEmit)"
# Expo/Metro and native autolinking expect a flat node_modules; still project-local
MOBILE_NPMRC = "engine-strict=true\nnode-linker=hoisted\n"

INDEX_TS = """/**
 * @file App entry: registers the root component for Expo Go and native builds.
 */
import { registerRootComponent } from "expo";

import App from "./src/entrypoints/App";

registerRootComponent(App);
"""

ENV_TS = """/**
 * @file Configuration layer: the only place that reads `process.env`.
 *
 * Expo inlines `EXPO_PUBLIC_*` variables into the app bundle at build time, so they are
 * visible to anyone who has the app: never put secrets here (keys stay on the backend).
 */

/** Settings the rest of the app receives as arguments. */
export interface AppConfig {
  /** Backend base URL; 127.0.0.1 works in the iOS Simulator and, with `adb reverse`, the Android emulator. */
  apiUrl: string;
  /** Minimum log level: debug | info | warn | error. */
  logLevel: string;
  /** Request timeout in milliseconds. */
  timeoutMs: number;
}

/**
 * Read the app settings from `EXPO_PUBLIC_*` variables (`mobile/.env`).
 * @returns The configuration with defaults for local development.
 */
export function loadConfig(): AppConfig {
  return {
    apiUrl: (process.env.EXPO_PUBLIC_API_URL ?? "http://127.0.0.1:8000").replace(/\\/$/, ""),
    logLevel: process.env.EXPO_PUBLIC_LOG_LEVEL ?? "info",
    timeoutMs: Number(process.env.EXPO_PUBLIC_TIMEOUT_MS ?? "10000"),
  };
}
"""

LOGGER_TS = """/**
 * @file Small leveled logger so every module logs the same way.
 *
 * Lines look like `INFO [adapters/api] GET /health -> 200 (35 ms)`. They appear in the
 * Expo CLI terminal and in the device log (Xcode / Android Studio Logcat).
 */

const LEVELS = ["debug", "info", "warn", "error"] as const;
type Level = (typeof LEVELS)[number];

/** Logger bound to one module name. */
export interface Logger {
  debug: (message: string, ...details: unknown[]) => void;
  info: (message: string, ...details: unknown[]) => void;
  warn: (message: string, ...details: unknown[]) => void;
  error: (message: string, ...details: unknown[]) => void;
}

/**
 * Create a logger for one module.
 * @param scope Module name shown on every line, e.g. `services/greeting`.
 * @param minLevel Lowest level to print (from `AppConfig.logLevel`).
 * @returns The logger.
 */
export function createLogger(scope: string, minLevel: string = "info"): Logger {
  const threshold = Math.max(0, LEVELS.indexOf(minLevel as Level));
  /**
   * Build the print function for one level.
   * @param level Level written at the start of each line.
   * @returns Function that prints a message (and optional details) when the level is enabled.
   */
  const emit =(level: Level) => (message: string, ...details: unknown[]): void => {
    if (LEVELS.indexOf(level) < threshold) {
      return;
    }
    const line = `${level.toUpperCase()} [${scope}] ${message}`;
    const sink = level === "error" ? console.error : level === "warn" ? console.warn : console.log;
    sink(line, ...details);
  };
  return { debug: emit("debug"), info: emit("info"), warn: emit("warn"), error: emit("error") };
}
"""

MODELS_TS = """/**
 * @file Domain layer: plain data types shared by services, adapters and screens (no I/O).
 */

/** A request to greet one user. */
export interface GreetingRequest {
  /** Name typed by the user (may contain surrounding spaces). */
  userName: string;
}

/** Result shown on screen. */
export interface GreetingResult {
  /** Final greeting text. */
  message: string;
}
"""

GREETING_TS = """/**
 * @file Services layer: pure business logic (no React, no network), unit-tested with `node --test`.
 *
 * Only type imports from other modules here, so Node can run the file directly in tests.
 */
import type { GreetingRequest, GreetingResult } from "../domain/models";

/**
 * Build a greeting for the requested user.
 * @param request The user's request; blank names fall back to "World".
 * @returns The greeting message.
 */
export function createGreeting(request: GreetingRequest): GreetingResult {
  const name = request.userName.trim() || "World";
  return { message: `Hello, ${name}!` };
}
"""

API_TS = """/**
 * @file Adapters layer: HTTP client for the project's backend (timeout, logging, typed errors).
 */
import type { AppConfig } from "../config/env";
import { createLogger } from "../config/logger";

/** Backend health answer (`GET /health`). */
export interface Health {
  status: string;
  environment: string;
}

/**
 * Call `GET /health` on the backend.
 * @param config App settings (base URL, timeout, log level).
 * @returns The health answer.
 * @throws Error when the backend is unreachable, too slow or answers with an error status.
 */
export async function fetchHealth(config: AppConfig): Promise<Health> {
  const log = createLogger("adapters/api", config.logLevel);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), config.timeoutMs);
  const started = Date.now();
  try {
    const res = await fetch(`${config.apiUrl}/health`, { signal: controller.signal });
    log.info(`GET /health -> ${res.status} (${Date.now() - started} ms)`);
    if (!res.ok) {
      throw new Error(`backend answered ${res.status}`);
    }
    return (await res.json()) as Health;
  } catch (err) {
    log.error(`GET /health failed after ${Date.now() - started} ms`, err);
    throw err;
  } finally {
    clearTimeout(timer);
  }
}
"""

APP_TSX = """/**
 * @file Entrypoints layer: the root screen. Wires config, services and adapters together.
 */
import { StatusBar } from "expo-status-bar";
import { useMemo, useState } from "react";
import { Button, StyleSheet, Text, TextInput, View } from "react-native";

import { fetchHealth } from "../adapters/api";
import { loadConfig } from "../config/env";
import { createLogger } from "../config/logger";
import { createGreeting } from "../services/greeting";

/**
 * Root screen: greet a name and check that the backend is reachable.
 * @returns The screen.
 */
export default function App(): React.JSX.Element {
  const config = useMemo(loadConfig, []);
  const log = useMemo(() => createLogger("entrypoints/App", config.logLevel), [config]);
  const [name, setName] = useState("");
  const [backend, setBackend] = useState("not checked");
  const greeting = createGreeting({ userName: name }).message;

  /**
   * Ask the backend for `/health` and show the result.
   * @returns Nothing; updates the screen state.
   */
  const checkBackend = async (): Promise<void> => {
    try {
      const health = await fetchHealth(config);
      setBackend(`${health.status} (${health.environment})`);
    } catch {
      setBackend(`unreachable: ${config.apiUrl}`);
    }
    log.info("backend check finished");
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>{greeting}</Text>
      <TextInput style={styles.input} placeholder="Your name" value={name} onChangeText={setName} />
      <Button title="Check backend" onPress={checkBackend} />
      <Text>Backend: {backend}</Text>
      <StatusBar style="auto" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: "center", justifyContent: "center", gap: 16, padding: 24 },
  title: { fontSize: 24, fontWeight: "600" },
  input: { alignSelf: "stretch", borderWidth: 1, borderColor: "#ccc", borderRadius: 8, padding: 12, fontSize: 16 },
});
"""

GREETING_TEST = """/**
 * @file Unit tests for the greeting service (run with `node --test`; Node strips the types).
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { createGreeting } from "../src/services/greeting.ts";

test("greets a name", () => {
  assert.equal(createGreeting({ userName: "Ann" }).message, "Hello, Ann!");
});

test("blank name falls back to World", () => {
  assert.equal(createGreeting({ userName: "   " }).message, "Hello, World!");
});
"""

TSCONFIG = {
    "extends": "expo/tsconfig.base",
    "compilerOptions": {
        "strict": True,
        "noEmit": True,
        # Tests import `../src/x.ts`; erasable syntax only, so Node can strip the types
        "allowImportingTsExtensions": True,
        "erasableSyntaxOnly": True,
        # TypeScript 6 no longer loads @types/* automatically; React Native ships its own types
        "types": ["node"],
    },
}

ENV_EXAMPLE = """# Copy to `mobile/.env`. Expo puts EXPO_PUBLIC_* values INTO the app: no secrets here.
# iOS Simulator: 127.0.0.1 reaches the Mac. Android emulator: run `adb reverse tcp:8000 tcp:8000` first.
EXPO_PUBLIC_API_URL=http://127.0.0.1:8000
EXPO_PUBLIC_LOG_LEVEL=info
EXPO_PUBLIC_TIMEOUT_MS=10000
"""

MOBILE_GUIDE = """# 手機 App（Expo：React Native + TypeScript，Android 與 iOS 共用）

## 1. 安裝（只裝在 `mobile/node_modules`，不污染主機）

```bash
pnpm install
```

需要的系統工具（`agentctl doctor` 會檢查）：
- iOS 模擬器：App Store 安裝 **Xcode**，打開一次同意授權，再到 Settings → Components 下載 iOS Simulator。
- Android 模擬器：`brew bundle --file ../Brewfile` 安裝 Android Studio，打開後用 Device Manager 建立一台模擬器。
- 開發時也可以只用手機上的 **Expo Go** App（見第 3 點）。

## 2. 預設：在模擬器執行

模擬器可以用 `127.0.0.1` 連到這台 Mac，所以「本機服務只綁 127.0.0.1」的規則不變。

```bash
pnpm ios
```

```bash
pnpm android
```

Android 模擬器要連 Mac 上的後端（例如 FastAPI 的 8000 port），先轉接一次：

```bash
adb reverse tcp:8000 tcp:8000
```

## 3. 用真的手機測試：只用 tunnel

手機裝 Expo Go，掃描終端機的 QR code。**一律用 `--tunnel`**，不要把開發伺服器開放到區域網路：

```bash
pnpm tunnel
```

- tunnel 只轉送 App 的程式碼（Metro）。後端仍只綁 `127.0.0.1`，手機連不到 → 需要後端的功能請在模擬器測試。
- 一定要讓實機連後端時，先問使用者，並用另一條 tunnel 或測試用的雲端環境，**不可改成 0.0.0.0**。
- `@expo/ngrok` 是本資料夾的 devDependency，不需要全域安裝。

> pnpm 會擋下「剛發布不久」的套件（防供應鏈攻擊）。Expo 更新很頻繁，安裝時 pnpm 可能自動在 `pnpm-workspace.yaml` 寫入例外（只限列出的版本）。這個檔案要 commit，讓其他電腦與 CI 安裝結果一致；每次 diff 出現新例外時，確認是 Expo 官方套件再 commit。

## 4. 規則

- 分層同其他程式：`config`（唯一讀 `process.env`）→ `domain` → `services`（純邏輯）→ `adapters`（網路、儲存）→ `entrypoints`（畫面）。
- 每個檔案開頭 `@file` 說明；每個函式 JSDoc 與每個 `@param`（`code-review-guard` 會檢查）。
- Log 用 `createLogger("<層>/<模組>")`，不要直接 `console.log`；錯誤一定記 `log.error`。
- `EXPO_PUBLIC_*` 會被打包進 App，**任何人都看得到**：金鑰只放後端。
- 簽章檔（`*.jks`、`*.keystore`、`*.p8`、`*.p12`、`*.mobileprovision`）不進 git（pre-commit 會擋），放 `~/.config/<專案>/`。
- `mobile/ios/`、`mobile/android/` 是 `expo prebuild` 產生的，不進 git；需要原生模組時改用 development build。

## 5. 測試與型別檢查

```bash
pnpm test
```

```bash
pnpm typecheck
```

`services/` 只用 `import type` 引用其他模組，所以 Node 能直接執行 TypeScript 測試，不需要安裝 Jest。

## 6. 版本與上架（之後再做）

- Expo SDK {sdk}。升級 SDK 後在本資料夾執行 `pnpm exec expo install --fix`，讓 react / react-native 版本對齊。
- App 的版本號在 `app.json`（`expo.version`），和後端版本分開管理。
- 上架需要 Apple Developer（每年 USD 99）與 Google Play（一次 USD 25）帳號；建置用 EAS Build。
"""


def app_json(project_name: str) -> str:
    """Render `mobile/app.json` (Expo app settings).

    Args:
        project_name: Display name of the app.

    Returns:
        JSON text.
    """
    slug = npm_slug(project_name)
    expo = {
        "name": project_name,
        "slug": slug,
        "version": "0.1.0",
        "orientation": "portrait",
        "userInterfaceStyle": "automatic",
        "ios": {"supportsTablet": True},
        "android": {"predictiveBackGestureEnabled": False},
    }
    return json.dumps({"expo": expo}, indent=2, ensure_ascii=False) + "\n"


def mobile_package_json(project_name: str, pnpm_version: str) -> str:
    """Render `mobile/package.json` with the Expo SDK dependencies and local tools.

    Args:
        project_name: Project name (npm package name is derived from it).
        pnpm_version: pnpm version for `packageManager` (empty to omit).

    Returns:
        JSON text.
    """
    data: dict[str, Any] = {"name": f"{npm_slug(project_name)}-mobile", "version": "0.1.0", "private": True, "main": "index.ts"}
    if pnpm_version:
        data["packageManager"] = f"pnpm@{pnpm_version}"
    data["engines"] = NPM_BLOCK_ENGINES
    data["scripts"] = {
        "start": "expo start",
        "ios": "expo start --ios",
        "android": "expo start --android",
        "tunnel": "expo start --tunnel",
        "test": "node --test",
        "typecheck": "tsc --noEmit",
    }
    data["dependencies"] = DEPENDENCIES
    data["devDependencies"] = DEV_DEPENDENCIES
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def scaffold_mobile_pack(target_dir: Path, project_name: str, pnpm_version: str) -> None:
    """Create the Expo app in `mobile/`.

    Args:
        target_dir: Project root directory.
        project_name: Project name (app display name).
        pnpm_version: pnpm version for `packageManager` (empty to omit).
    """
    mobile = target_dir / "mobile"
    _write(mobile / "package.json", mobile_package_json(project_name, pnpm_version))
    _write(mobile / ".npmrc", MOBILE_NPMRC)
    _write(mobile / "app.json", app_json(project_name))
    _write(mobile / "tsconfig.json", json.dumps(TSCONFIG, indent=2) + "\n")
    _write(mobile / ".env.example", ENV_EXAMPLE)
    _write(mobile / "index.ts", INDEX_TS)
    src = mobile / "src"
    _write(src / "config" / "env.ts", ENV_TS)
    _write(src / "config" / "logger.ts", LOGGER_TS)
    _write(src / "domain" / "models.ts", MODELS_TS)
    _write(src / "services" / "greeting.ts", GREETING_TS)
    _write(src / "adapters" / "api.ts", API_TS)
    _write(src / "entrypoints" / "App.tsx", APP_TSX)
    _write(mobile / "test" / "greeting.test.ts", GREETING_TEST)
    _write(mobile / "MOBILE.md", MOBILE_GUIDE.replace("{sdk}", EXPO_SDK))
    _write(target_dir / "Brewfile", BREWFILE)


BREWFILE = """# System tools for this project (check: `agentctl doctor`; install: `brew bundle --file Brewfile`).
# Xcode (iOS Simulator) comes from the App Store, not Homebrew.
brew "watchman"          # file watching for Metro (recommended by Expo)
cask "android-studio"    # Android SDK + emulator
"""
