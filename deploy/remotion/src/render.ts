/**
 * Remotion render wrapper — thin layer over `@remotion/renderer` and
 * `@remotion/bundler`. The Express server in `server.ts` calls this module
 * rather than shelling out to the `remotion` CLI: we keep everything in
 * process so props can be passed as real JS objects and so we avoid
 * shell-escaping pitfalls.
 */
import path from "node:path";
import { fileURLToPath } from "node:url";

import { bundle } from "@remotion/bundler";
import {
  renderMedia,
  selectComposition,
  type RenderMediaOnProgress,
} from "@remotion/renderer";

/** Templates registered in src/index.tsx. Keep this synchronized with that file. */
export type TemplateId = "bar_chart" | "number_ticker" | "line_chart";

export const TEMPLATE_IDS: readonly TemplateId[] = [
  "bar_chart",
  "number_ticker",
  "line_chart",
] as const;

/** Render fps for every composition — must match src/index.tsx. */
const FPS = 30;

export interface RenderInput {
  templateId: TemplateId;
  /** Serializable props for the target composition. */
  props: Record<string, unknown>;
  /** Target duration in seconds; clamped to [0.5, 120]. */
  targetDurationS: number;
  /** Absolute output path for the MP4. Parent directory must already exist. */
  outputPath: string;
  /** Optional audio track to mux in. If `null`, the MP4 is silent. */
  audioTrackUrl?: string | null;
}

export interface RenderResult {
  outputPath: string;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
}

/**
 * Resolve the project root (the directory that contains package.json).
 * `import.meta.url` points at the compiled .js file inside dist/, so we
 * walk one level up.
 */
function projectRoot(): string {
  const here = path.dirname(fileURLToPath(import.meta.url));
  // here = /app/dist  →  parent = /app
  return path.resolve(here, "..");
}

/**
 * Bundle the Remotion entry point. Cached across render calls so we pay
 * the webpack cost exactly once per process lifetime.
 *
 * We export this so the server can warm the bundle at startup and surface
 * bundle errors via the /healthz log output rather than the first /render.
 */
let cachedBundlePromise: Promise<string> | null = null;
export async function getBundle(): Promise<string> {
  if (cachedBundlePromise === null) {
    const entry = path.join(projectRoot(), "src", "index.tsx");
    cachedBundlePromise = bundle({
      entryPoint: entry,
      webpackOverride: (config) => ({
        ...config,
        resolve: {
          ...config.resolve,
          extensionAlias: {
            ...(config.resolve?.extensionAlias ?? {}),
            ".js": [".ts", ".tsx", ".js"],
          },
        },
      }),
    });
  }
  return cachedBundlePromise;
}

/**
 * Render a single composition to MP4 and return metadata about the output.
 * Throws on any renderer or bundler failure; callers should wrap in try/catch.
 */
export async function renderTemplate(
  input: RenderInput,
  onProgress?: RenderMediaOnProgress,
): Promise<RenderResult> {
  const bundleLocation = await getBundle();

  const clampedSeconds = Math.max(0.5, Math.min(input.targetDurationS, 120));
  const durationInFrames = Math.max(1, Math.round(clampedSeconds * FPS));

  const composition = await selectComposition({
    serveUrl: bundleLocation,
    id: input.templateId,
    inputProps: input.props,
  });

  // Override the composition's default duration with the request's target.
  const finalComposition = {
    ...composition,
    durationInFrames,
    fps: FPS,
  };

  // Remotion renders the composition's own `<Audio>` sources into the MP4.
  // The engagement layer does NOT mux external audio inside Remotion: the
  // Python sidecar handles voiceover + SFX concatenation downstream via
  // ffmpeg. The `audio_url` field on the API is therefore accepted but
  // unused here today — kept in the wire contract for a future in-process
  // mux option. See Unit C3 of the engagement-v2 plan.
  await renderMedia({
    composition: finalComposition,
    serveUrl: bundleLocation,
    codec: "h264",
    outputLocation: input.outputPath,
    inputProps: input.props,
    onProgress,
    chromiumOptions: {
      disableWebSecurity: false,
    },
  });
  // Silence the unused-param lint for audioTrackUrl without changing the
  // exported type (future in-process mux will consume it).
  void input.audioTrackUrl;

  return {
    outputPath: input.outputPath,
    durationInFrames,
    fps: FPS,
    width: finalComposition.width,
    height: finalComposition.height,
  };
}
