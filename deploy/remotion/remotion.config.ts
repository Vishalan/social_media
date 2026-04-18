/**
 * Remotion configuration for the CommonCreed chart renderer.
 *
 * This file is consumed by the Remotion CLI/bundler when you run `npx remotion
 * studio` locally; it is NOT imported by the production HTTP server (server.ts
 * invokes the renderer programmatically with an explicit entry point). Keeping
 * it here still matters because it fixes the studio entry point and ensures
 * the bundler picks up the same compositions the server does.
 */
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setConcurrency(1);

// Single entry point that registers all three compositions (bar_chart,
// number_ticker, line_chart). See src/index.tsx.
Config.setEntryPoint("./src/index.tsx");
